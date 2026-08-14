"""Add durable Theme-family and inactive Website configuration records.

Revision ID: 20260813_0045
Revises: 20260810_0044
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text


revision = "20260813_0045"
down_revision = "20260810_0044"
branch_labels = None
depends_on = None


TABLES = (
    "themefamily",
    "themefamilyversion",
    "websitethemeconfiguration",
    "websitethemecomponentconfiguration",
    "themeconfigurationaudit",
)

_INDEX_TABLE_PREFIXES = {
    "themefamily": "tf",
    "themefamilyversion": "tfv",
    "websitethemeconfiguration": "wtc",
    "websitethemecomponentconfiguration": "wtcc",
    "themeconfigurationaudit": "tca",
}


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    precreated = existing.intersection(TABLES)
    if precreated:
        raise RuntimeError(
            "Durable Theme configuration migration refuses pre-created tables; "
            "the additive migration must create the complete governed contract."
        )

    op.create_table(
        "themefamily",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("family_key", sa.String(length=120), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("provider_source_identity", sa.String(length=240), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("retired_by", sa.String(length=160), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('registered','retired')",
            name="ck_themefamily_lifecycle",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_themefamily_fingerprint",
        ),
        sa.CheckConstraint(
            "(lifecycle_status = 'registered' AND retired_by IS NULL AND retired_at IS NULL) "
            "OR (lifecycle_status = 'retired' AND retired_by IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_themefamily_retirement",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("family_key", name="uq_themefamily_key"),
    )
    _index("themefamily", "family_key")
    _index("themefamily", "lifecycle_status")
    _index("themefamily", "integrity_fingerprint")

    op.create_table(
        "themefamilyversion",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_family_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=32), nullable=False),
        sa.Column("production_ready", sa.Boolean(), nullable=False),
        sa.Column("source_commit", sa.String(length=40), nullable=False),
        sa.Column("compatibility_identity", sa.String(length=64), nullable=False),
        sa.Column("supported_component_contracts", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("retired_by", sa.String(length=160), nullable=True),
        sa.Column("retired_at", sa.DateTime(), nullable=True),
        sa.Column("supersedes_theme_family_version_id", sa.Integer(), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('preview_candidate','approved','retired')",
            name="ck_themefamilyversion_lifecycle",
        ),
        sa.CheckConstraint("version >= 1", name="ck_themefamilyversion_version"),
        sa.CheckConstraint(
            "production_ready = false OR lifecycle_status = 'approved'",
            name="ck_themefamilyversion_production_ready",
        ),
        sa.CheckConstraint(
            "length(source_commit) = 40 AND source_commit = lower(source_commit)",
            name="ck_themefamilyversion_source_commit",
        ),
        sa.CheckConstraint(
            "length(compatibility_identity) = 64 "
            "AND compatibility_identity = lower(compatibility_identity) "
            "AND length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_themefamilyversion_fingerprints",
        ),
        sa.CheckConstraint(
            "supersedes_theme_family_version_id IS NULL "
            "OR supersedes_theme_family_version_id != id",
            name="ck_themefamilyversion_not_self",
        ),
        sa.CheckConstraint(
            "(lifecycle_status != 'retired' AND retired_by IS NULL AND retired_at IS NULL) "
            "OR (lifecycle_status = 'retired' AND retired_by IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_themefamilyversion_retirement",
        ),
        sa.ForeignKeyConstraint(["theme_family_id"], ["themefamily.id"]),
        sa.ForeignKeyConstraint(
            ["supersedes_theme_family_version_id"],
            ["themefamilyversion.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "theme_family_id",
            "version",
            name="uq_themefamilyversion_family_version",
        ),
        sa.UniqueConstraint(
            "compatibility_identity",
            name="uq_themefamilyversion_compatibility",
        ),
        sa.UniqueConstraint(
            "supersedes_theme_family_version_id",
            name="uq_themefamilyversion_successor",
        ),
    )
    for column in (
        "theme_family_id",
        "lifecycle_status",
        "source_commit",
        "compatibility_identity",
        "supersedes_theme_family_version_id",
        "integrity_fingerprint",
    ):
        _index("themefamilyversion", column)

    op.create_table(
        "websitethemeconfiguration",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("business_id", sa.Integer(), nullable=False),
        sa.Column("theme_family_version_id", sa.Integer(), nullable=False),
        sa.Column("configuration_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column("creation_rationale", sa.String(length=2000), nullable=False),
        sa.Column("approved_by", sa.String(length=160), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("activated_by", sa.String(length=160), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("rollback_by", sa.String(length=160), nullable=True),
        sa.Column("rollback_at", sa.DateTime(), nullable=True),
        sa.Column("materialized_theme_id", sa.Integer(), nullable=True),
        sa.Column("website_theme_selection_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_configuration_id", sa.Integer(), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "lifecycle_status IN ('draft','approved','active','superseded','retired')",
            name="ck_websitethemeconfiguration_lifecycle",
        ),
        sa.CheckConstraint("version >= 1", name="ck_websitethemeconfiguration_version"),
        sa.CheckConstraint(
            "(version = 1 AND supersedes_configuration_id IS NULL) "
            "OR (version > 1 AND supersedes_configuration_id IS NOT NULL)",
            name="ck_websitethemeconfiguration_lineage",
        ),
        sa.CheckConstraint(
            "supersedes_configuration_id IS NULL OR supersedes_configuration_id != id",
            name="ck_websitethemeconfiguration_not_self",
        ),
        sa.CheckConstraint(
            "(materialized_theme_id IS NULL AND website_theme_selection_id IS NULL) "
            "OR (materialized_theme_id IS NOT NULL AND website_theme_selection_id IS NOT NULL)",
            name="ck_websitethemeconfiguration_selection_pair",
        ),
        sa.CheckConstraint(
            "(approved_by IS NULL AND approved_at IS NULL) "
            "OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_websitethemeconfiguration_approval_pair",
        ),
        sa.CheckConstraint(
            "lifecycle_status NOT IN ('approved','active') "
            "OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_websitethemeconfiguration_approved_evidence",
        ),
        sa.CheckConstraint(
            "(activated_by IS NULL AND activated_at IS NULL) "
            "OR (activated_by IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_websitethemeconfiguration_activation_pair",
        ),
        sa.CheckConstraint(
            "lifecycle_status != 'active' "
            "OR (activated_by IS NOT NULL AND activated_at IS NOT NULL "
            "AND materialized_theme_id IS NOT NULL "
            "AND website_theme_selection_id IS NOT NULL)",
            name="ck_websitethemeconfiguration_active_evidence",
        ),
        sa.CheckConstraint(
            "(rollback_by IS NULL AND rollback_at IS NULL) "
            "OR (rollback_by IS NOT NULL AND rollback_at IS NOT NULL)",
            name="ck_websitethemeconfiguration_rollback_pair",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_websitethemeconfiguration_fingerprint",
        ),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
        sa.ForeignKeyConstraint(
            ["theme_family_version_id"],
            ["themefamilyversion.id"],
        ),
        sa.ForeignKeyConstraint(["materialized_theme_id"], ["theme.id"]),
        sa.ForeignKeyConstraint(
            ["website_theme_selection_id"],
            ["websitethemeselection.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_configuration_id"],
            ["websitethemeconfiguration.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_id",
            "theme_family_version_id",
            "configuration_key",
            "version",
            name="uq_websitethemeconfiguration_scope_version",
        ),
        sa.UniqueConstraint(
            "supersedes_configuration_id",
            name="uq_websitethemeconfiguration_successor",
        ),
    )
    for column in (
        "website_id",
        "business_id",
        "theme_family_version_id",
        "configuration_key",
        "lifecycle_status",
        "materialized_theme_id",
        "website_theme_selection_id",
        "supersedes_configuration_id",
        "integrity_fingerprint",
    ):
        _index("websitethemeconfiguration", column)
    op.create_index(
        "uq_websitethemeconfiguration_current",
        "websitethemeconfiguration",
        ["website_id", "theme_family_version_id", "configuration_key"],
        unique=True,
        postgresql_where=sa.text(
            "lifecycle_status IN ('draft','approved','active')"
        ),
        sqlite_where=sa.text("lifecycle_status IN ('draft','approved','active')"),
    )

    op.create_table(
        "websitethemecomponentconfiguration",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_theme_configuration_id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=True),
        sa.Column("theme_family_version_id", sa.Integer(), nullable=False),
        sa.Column("component_instance_key", sa.String(length=120), nullable=False),
        sa.Column("component_key", sa.String(length=80), nullable=False),
        sa.Column("component_contract_version", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=24), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("variant", sa.String(length=120), nullable=False),
        sa.Column("placement", sa.String(length=120), nullable=False),
        sa.Column("responsive_visibility", sa.JSON(), nullable=False),
        sa.Column("configuration_payload", sa.JSON(), nullable=False),
        sa.Column("effective_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("approval_identity", sa.String(length=160), nullable=True),
        sa.Column("created_by", sa.String(length=160), nullable=False),
        sa.Column("updated_by", sa.String(length=160), nullable=False),
        sa.Column("activation_identity", sa.String(length=160), nullable=True),
        sa.Column("activated_at", sa.DateTime(), nullable=True),
        sa.Column("rollback_identity", sa.String(length=160), nullable=True),
        sa.Column("rollback_at", sa.DateTime(), nullable=True),
        sa.Column("destination_component_configuration_id", sa.Integer(), nullable=True),
        sa.Column("overrides_component_configuration_id", sa.Integer(), nullable=True),
        sa.Column("supersedes_component_configuration_id", sa.Integer(), nullable=True),
        sa.Column("integrity_fingerprint", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "scope_type IN ('website_default','page_override')",
            name="ck_themecomponentconfiguration_scope",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('current','superseded')",
            name="ck_themecomponentconfiguration_lifecycle",
        ),
        sa.CheckConstraint(
            "component_contract_version >= 1 AND revision >= 1",
            name="ck_themecomponentconfiguration_versions",
        ),
        sa.CheckConstraint(
            "(scope_type = 'website_default' AND planned_page_id IS NULL "
            "AND overrides_component_configuration_id IS NULL) "
            "OR (scope_type = 'page_override' AND planned_page_id IS NOT NULL "
            "AND overrides_component_configuration_id IS NOT NULL)",
            name="ck_themecomponentconfiguration_page_scope",
        ),
        sa.CheckConstraint(
            "(revision = 1 AND supersedes_component_configuration_id IS NULL) "
            "OR (revision > 1 AND supersedes_component_configuration_id IS NOT NULL)",
            name="ck_themecomponentconfiguration_lineage",
        ),
        sa.CheckConstraint(
            "supersedes_component_configuration_id IS NULL "
            "OR supersedes_component_configuration_id != id",
            name="ck_themecomponentconfiguration_not_self",
        ),
        sa.CheckConstraint(
            "destination_component_configuration_id IS NULL "
            "OR destination_component_configuration_id != id",
            name="ck_themecomponentconfiguration_destination_not_self",
        ),
        sa.CheckConstraint(
            "overrides_component_configuration_id IS NULL "
            "OR overrides_component_configuration_id != id",
            name="ck_themecomponentconfiguration_override_not_self",
        ),
        sa.CheckConstraint(
            "expires_at IS NULL OR effective_at IS NULL OR expires_at >= effective_at",
            name="ck_themecomponentconfiguration_dates",
        ),
        sa.CheckConstraint(
            "(activation_identity IS NULL AND activated_at IS NULL) "
            "OR (activation_identity IS NOT NULL AND activated_at IS NOT NULL)",
            name="ck_themecomponentconfiguration_activation_pair",
        ),
        sa.CheckConstraint(
            "(rollback_identity IS NULL AND rollback_at IS NULL) "
            "OR (rollback_identity IS NOT NULL AND rollback_at IS NOT NULL)",
            name="ck_themecomponentconfiguration_rollback_pair",
        ),
        sa.CheckConstraint(
            "length(integrity_fingerprint) = 64 "
            "AND integrity_fingerprint = lower(integrity_fingerprint)",
            name="ck_themecomponentconfiguration_fingerprint",
        ),
        sa.ForeignKeyConstraint(
            ["website_theme_configuration_id"],
            ["websitethemeconfiguration.id"],
        ),
        sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
        sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
        sa.ForeignKeyConstraint(
            ["theme_family_version_id"],
            ["themefamilyversion.id"],
        ),
        sa.ForeignKeyConstraint(
            ["destination_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
        ),
        sa.ForeignKeyConstraint(
            ["overrides_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "website_theme_configuration_id",
            "component_instance_key",
            "revision",
            name="uq_themecomponentconfiguration_instance_revision",
        ),
        sa.UniqueConstraint(
            "supersedes_component_configuration_id",
            name="uq_themecomponentconfiguration_successor",
        ),
    )
    for column in (
        "website_theme_configuration_id",
        "website_id",
        "planned_page_id",
        "theme_family_version_id",
        "component_instance_key",
        "component_key",
        "scope_type",
        "lifecycle_status",
        "destination_component_configuration_id",
        "overrides_component_configuration_id",
        "supersedes_component_configuration_id",
        "integrity_fingerprint",
    ):
        _index("websitethemecomponentconfiguration", column)
    op.create_index(
        "uq_themecomponentconfiguration_current_website_instance",
        "websitethemecomponentconfiguration",
        ["website_theme_configuration_id", "component_instance_key"],
        unique=True,
        postgresql_where=sa.text(
            "lifecycle_status = 'current' AND scope_type = 'website_default'"
        ),
        sqlite_where=sa.text(
            "lifecycle_status = 'current' AND scope_type = 'website_default'"
        ),
    )
    op.create_index(
        "uq_themecomponentconfiguration_current_page_override",
        "websitethemecomponentconfiguration",
        [
            "website_theme_configuration_id",
            "planned_page_id",
            "overrides_component_configuration_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "lifecycle_status = 'current' AND scope_type = 'page_override'"
        ),
        sqlite_where=sa.text(
            "lifecycle_status = 'current' AND scope_type = 'page_override'"
        ),
    )

    op.create_table(
        "themeconfigurationaudit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_family_id", sa.Integer(), nullable=True),
        sa.Column("theme_family_version_id", sa.Integer(), nullable=True),
        sa.Column("website_theme_configuration_id", sa.Integer(), nullable=True),
        sa.Column("component_configuration_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=48), nullable=False),
        sa.Column("actor", sa.String(length=160), nullable=False),
        sa.Column("rationale", sa.String(length=2000), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "(CASE WHEN theme_family_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN theme_family_version_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN website_theme_configuration_id IS NULL THEN 0 ELSE 1 END + "
            "CASE WHEN component_configuration_id IS NULL THEN 0 ELSE 1 END) = 1",
            name="ck_themeconfigurationaudit_exact_target",
        ),
        sa.CheckConstraint(
            "action_type IN ('family_registered','family_version_registered',"
            "'family_version_approved','website_draft_created',"
            "'website_configuration_revision_created','website_configuration_approved',"
            "'website_configuration_activated','website_configuration_superseded',"
            "'website_configuration_rolled_back','website_configuration_retired',"
            "'component_created','component_revision_created','component_superseded',"
            "'component_activated','component_rolled_back',"
            "'family_retired','family_version_retired')",
            name="ck_themeconfigurationaudit_action",
        ),
        sa.CheckConstraint(
            "length(snapshot_hash) = 64 AND snapshot_hash = lower(snapshot_hash)",
            name="ck_themeconfigurationaudit_hash",
        ),
        sa.ForeignKeyConstraint(["theme_family_id"], ["themefamily.id"]),
        sa.ForeignKeyConstraint(
            ["theme_family_version_id"],
            ["themefamilyversion.id"],
        ),
        sa.ForeignKeyConstraint(
            ["website_theme_configuration_id"],
            ["websitethemeconfiguration.id"],
        ),
        sa.ForeignKeyConstraint(
            ["component_configuration_id"],
            ["websitethemecomponentconfiguration.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_hash", name="uq_themeconfigurationaudit_hash"),
    )
    for column in (
        "theme_family_id",
        "theme_family_version_id",
        "website_theme_configuration_id",
        "component_configuration_id",
        "action_type",
        "snapshot_hash",
        "created_at",
    ):
        _index("themeconfigurationaudit", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in TABLES:
        if table in existing and bind.execute(
            text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one():
            raise RuntimeError(
                "Cannot downgrade durable Theme configuration migration while governed records exist."
            )
    for table in reversed(TABLES):
        if table in existing:
            op.drop_table(table)


def _index(table: str, column: str) -> None:
    op.create_index(_index_identifier(table, column), table, [column], unique=False)


def _index_identifier(table: str, column: str) -> str:
    prefix = _INDEX_TABLE_PREFIXES[table]
    name = f"ix_{prefix}_{column}"
    if len(name) > 63:  # PostgreSQL NAMEDATALEN is 64 including the terminator.
        raise RuntimeError(f"Migration index identifier exceeds PostgreSQL's 63-byte limit: {name}")
    return name
