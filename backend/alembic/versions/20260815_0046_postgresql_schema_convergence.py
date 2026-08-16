"""Converge the two accepted 0045 schemas on one canonical contract.

Revision ID: 20260815_0046
Revises: 20260813_0045

The repaired clean-install 0045 schema and the pre-existing Atlas 0045 schema
are deliberately classified before any DDL is emitted.  Physical column
ordinal positions are not semantic inputs.  Exactly sixteen documented
foreign-key name pairs are payload-guarded aliases; every other foreign-key
name and every other discovered semantic difference is identity-sensitive.
"""

from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Literal

from alembic import op
import sqlalchemy as sa


revision = "20260815_0046"
down_revision = "20260813_0045"
branch_labels = None
depends_on = None


SourceVariant = Literal["clean", "active", "canonical"]
CATALOG_MANIFEST_VERSION = "atlas-pg16-semantic-v1"
SUPPORTED_POSTGRESQL_MAJOR = 16


RUNTIME_TABLES = frozenset(
    {
        "wordpressmetadatastate",
        "wordpressmetadatasyncaudit",
        "wordpressqualityreview",
    }
)

# The sealed clean/active comparison found these 57 physical-position-only
# differences.  Column identity in the semantic manifest is table/name based,
# so no convergence DDL is emitted for them; keeping the complete inventory
# here makes that one normalization decision independently auditable.
ORDINAL_ONLY_COLUMNS = {
    "brandasset": (
        "replaces_brand_asset_id",
        "retired_at",
        "retired_by",
        "retirement_rationale",
    ),
    "city": ("notes", "status"),
    "draftingeligibilityassessment": (
        "assessed_at",
        "evidence",
        "local_value_findings",
        "reasons",
        "semantic_findings",
    ),
    "generatedpage": (
        "draft_content",
        "generated_at",
        "internal_notes",
        "last_reviewed_at",
        "last_reviewed_by",
        "qa_checked_at",
        "qa_result",
        "status",
        "wordpress_post_id",
        "wordpress_url",
    ),
    "imagemetadata": (
        "alt_text",
        "asset_url",
        "caption",
        "county_id",
        "exif_status",
        "file_name",
        "geo_city",
        "geo_state",
        "image_prompt",
        "image_title",
        "notes",
        "optimized_url",
        "original_filename",
        "reviewed_alt_text",
        "stored_filename",
        "thumbnail_url",
    ),
    "pageimageassignment": (
        "override_alt_text",
        "override_focal_x",
        "override_focal_y",
        "status",
    ),
    "plannedpage": ("generated_page_id", "planning_status"),
    "scopedmediaauthorization": (
        "approval_fingerprint",
        "asset_approved_at",
        "asset_approved_by",
        "assignment_version",
        "authorization_fingerprint",
        "authorization_rationale",
        "authorization_terms",
        "authorization_version",
        "authorized_at",
        "authorized_by",
        "lifecycle_status",
        "page_image_assignment_id",
        "reuse_policy",
        "supersedes_authorization_id",
    ),
}

# Only these sixteen accepted clean/active foreign-key name pairs are aliases.
# Every other foreign-key name remains identity-sensitive in the full catalog
# manifest.  The semantic key prevents an unrelated constraint from borrowing
# one of the accepted names.
FK_NAME_ALIASES = {
    (
        "generatedpageqaresult",
        ("website_id",),
        "website",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_website_id",
            "generatedpageqaresult_website_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("site_plan_id",),
        "siteplan",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_site_plan_id",
            "generatedpageqaresult_site_plan_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("planned_page_id",),
        "plannedpage",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_planned_page_id",
            "generatedpageqaresult_planned_page_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("generated_page_id",),
        "generatedpage",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_generated_page_id",
            "generatedpageqaresult_generated_page_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("latest_generated_page_revision_id",),
        "generatedpagerevision",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_latest_revision_id",
            "generatedpageqaresult_latest_generated_page_revision_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("page_composition_id",),
        "pagecomposition",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_page_composition_id",
            "generatedpageqaresult_page_composition_id_fkey",
        }
    ),
    (
        "generatedpageqaresult",
        ("supersedes_qa_result_id",),
        "generatedpageqaresult",
        ("id",),
    ): frozenset(
        {
            "fk_generatedpageqaresult_supersedes_id",
            "generatedpageqaresult_supersedes_qa_result_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("website_id",),
        "website",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_website_id",
            "scopedmediaauthorization_website_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("site_plan_id",),
        "siteplan",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_site_plan_id",
            "scopedmediaauthorization_site_plan_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("planned_page_id",),
        "plannedpage",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_planned_page_id",
            "scopedmediaauthorization_planned_page_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("generated_page_id",),
        "generatedpage",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_generated_page_id",
            "scopedmediaauthorization_generated_page_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("media_requirement_id",),
        "plannedpagemediarequirement",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_media_requirement_id",
            "scopedmediaauthorization_media_requirement_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("image_metadata_id",),
        "imagemetadata",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_image_metadata_id",
            "scopedmediaauthorization_image_metadata_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("page_image_assignment_id",),
        "pageimageassignment",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_assignment_id",
            "scopedmediaauthorization_page_image_assignment_id_fkey",
        }
    ),
    (
        "scopedmediaauthorization",
        ("supersedes_authorization_id",),
        "scopedmediaauthorization",
        ("id",),
    ): frozenset(
        {
            "fk_scopedmediaauth_supersedes_id",
            "scopedmediaauthorization_supersedes_authorization_id_fkey",
        }
    ),
    (
        "imagemetadata",
        ("county_id",),
        "county",
        ("id",),
    ): frozenset(
        {
            "fk_imagemetadata_county_id",
            "imagemetadata_county_id_fkey",
        }
    ),
}

# Frozen only from ledgered, exact 0045 fixtures.  These sentinels deliberately
# keep PostgreSQL fail-closed until the fixture manifests have been captured,
# independently compared, and replaced in source.  SQLite does not use them.
EXPECTED_CATALOG_MANIFEST_SHA256 = {
    "clean": "b3dc37debe6121b1026bf54fc0537168f98721484ffd3525257a929aaff0f6d3",
    "active": "2ff84ad392cb90c171676d0d90d2e482cf0404dcd57f55dcb8b703e0812a1ed1",
    "canonical": "e6026569f4e25a3566420b8855f52826cc5f378074accdb56221e1f6804d879f",
}

ACTIVE_TABLES = frozenset(
    {
        "alembic_version",
        "approvalaudit",
        "brand",
        "brandasset",
        "business",
        "city",
        "county",
        "draftingeligibilityassessment",
        "draftingeligibilitydisposition",
        "generatedpage",
        "generatedpageqaresult",
        "generatedpagerevision",
        "imagemetadata",
        "internallinkintent",
        "knowledgeblock",
        "navigationitem",
        "navigationset",
        "pagecomposition",
        "pageimageassignment",
        "plannedpage",
        "plannedpagemediarequirement",
        "planningrecord",
        "predraftdistinctnessbrief",
        "scopedmediaauthorization",
        "semanticcomponentdefinition",
        "service",
        "setting",
        "siteconnectionplanningrecord",
        "siteplan",
        "supportingpageauthorization",
        "theme",
        "themeconfigurationaudit",
        "themefamily",
        "themefamilyversion",
        "website",
        "websitecitycoveragedecision",
        "websitecountycoveragedecision",
        "websitecoverageplanningrecord",
        "websitedraftgenerationitem",
        "websitedraftgenerationrun",
        "websiteidentity",
        "websiteidentityassetassignment",
        "websitemediaplanningrecord",
        "websiteservicecitycoveragedecision",
        "websiteservicecountycoveragedecision",
        "websiteservicecoveragedecision",
        "websitethemecomponentconfiguration",
        "websitethemeconfiguration",
        "websitethemeselection",
        "wordpressactivationaudit",
        "wordpressbootstrapcleanupaudit",
        "wordpressbootstrapestablishmentaudit",
        "wordpresscacheawarerenderingaudit",
        "wordpressdeploymentaudit",
        "wordpressdeploymentnonce",
        "wordpressdeploymenttransition",
        "wordpressdraftaudit",
        "wordpressheadingcorrectionaudit",
        "wordpressmediasyncaudit",
        "wordpressmetadatalifecycleaudit",
        "wordpressmetadatastate",
        "wordpressmetadatasyncaudit",
        "wordpresspluginupgradeaudit",
        "wordpresspublishaudit",
        "wordpressqualityreview",
    }
)
CLEAN_TABLES = ACTIVE_TABLES - RUNTIME_TABLES
ACTIVE_SEQUENCES = frozenset(
    f"{table}_id_seq" for table in ACTIVE_TABLES if table != "alembic_version"
)
CLEAN_SEQUENCES = ACTIVE_SEQUENCES - frozenset(
    f"{table}_id_seq" for table in RUNTIME_TABLES
)


TIMESTAMPTZ_COLUMNS = frozenset(
    {
        *(f"{table}.{column}" for table in (
            "siteconnectionplanningrecord",
            "navigationset",
            "navigationitem",
            "internallinkintent",
            "websitecoverageplanningrecord",
            "websiteservicecoveragedecision",
            "websitecountycoveragedecision",
            "websitecitycoveragedecision",
            "websiteservicecitycoveragedecision",
        ) for column in ("created_at", "updated_at")),
        "siteconnectionplanningrecord.generated_at",
        "websitecoverageplanningrecord.generated_at",
        "websiteservicecoveragedecision.decided_at",
        "websitecountycoveragedecision.decided_at",
        "websitecitycoveragedecision.decided_at",
        "websiteservicecitycoveragedecision.decided_at",
    }
)


@dataclass(frozen=True)
class DefaultContract:
    type_name: str
    sql: str


SERVER_DEFAULTS: dict[str, DefaultContract] = {
    "city.priority": DefaultContract("character varying", "'Medium'"),
    "city.is_primary_market": DefaultContract("boolean", "false"),
    "generatedpage.generation_status": DefaultContract(
        "character varying", "'not_generated'"
    ),
    "generatedpage.qa_status": DefaultContract("character varying", "'not_run'"),
    "imagemetadata.image_role": DefaultContract("character varying", "'support'"),
    "imagemetadata.review_status": DefaultContract("character varying", "'pending'"),
    "imagemetadata.focal_x": DefaultContract("double precision", "0.5"),
    "imagemetadata.focal_y": DefaultContract("double precision", "0.5"),
    "pageimageassignment.display_preset": DefaultContract(
        "character varying", "'hero_desktop'"
    ),
    "wordpressactivationaudit.wordpress_write_count": DefaultContract("integer", "0"),
    "wordpressheadingcorrectionaudit.wordpress_write_count": DefaultContract(
        "integer", "0"
    ),
    "wordpressmetadatalifecycleaudit.wordpress_write_count": DefaultContract(
        "integer", "0"
    ),
    "wordpressmetadatalifecycleaudit.atlas_write_count": DefaultContract("integer", "0"),
    "wordpresspluginupgradeaudit.wordpress_write_count": DefaultContract("integer", "0"),
    "wordpresspluginupgradeaudit.atlas_write_count": DefaultContract("integer", "0"),
    "wordpressbootstrapcleanupaudit.wordpress_write_count": DefaultContract("integer", "0"),
    "wordpressbootstrapcleanupaudit.atlas_write_count": DefaultContract("integer", "0"),
    "wordpresscacheawarerenderingaudit.wordpress_write_count": DefaultContract(
        "integer", "0"
    ),
    "wordpresscacheawarerenderingaudit.cache_write_count": DefaultContract("integer", "0"),
    "wordpresscacheawarerenderingaudit.atlas_write_count": DefaultContract("integer", "0"),
    "wordpressbootstrapestablishmentaudit.inactive_checksum_verifiable": DefaultContract(
        "boolean", "false"
    ),
    "wordpressbootstrapestablishmentaudit.approved_residual_risk": DefaultContract(
        "boolean", "true"
    ),
    "wordpressbootstrapestablishmentaudit.wordpress_write_count": DefaultContract(
        "integer", "0"
    ),
    "wordpressbootstrapestablishmentaudit.cache_write_count": DefaultContract("integer", "0"),
    "wordpressbootstrapestablishmentaudit.atlas_write_count": DefaultContract("integer", "0"),
}


CHECKS_TO_ADD: dict[tuple[str, str], str] = {
    ("brandasset", "ck_brandasset_version"): "version >= 1",
    ("brandasset", "ck_brandasset_file_size"): "file_size >= 1",
    ("brandasset", "ck_brandasset_width"): "width >= 1",
    ("brandasset", "ck_brandasset_height"): "height >= 1",
    (
        "websiteidentityassetassignment",
        "ck_identityassetassignment_version",
    ): "version >= 1",
    (
        "semanticcomponentdefinition",
        "ck_semanticcomponentdefinition_version",
    ): "contract_version >= 1",
    ("pagecomposition", "ck_pagecomposition_version"): "composition_version >= 1",
    (
        "websitedraftgenerationrun",
        "ck_websitedraftgenerationrun_counts",
    ): (
        "expected_count >= 0 AND eligible_count >= 0 "
        "AND generated_count >= 0 AND already_drafted_count >= 0 "
        "AND skipped_count >= 0 AND blocked_count >= 0 "
        "AND deferred_count >= 0 AND excluded_count >= 0 "
        "AND stale_count >= 0 AND consolidation_count >= 0 "
        "AND error_count >= 0 AND processed_count >= 0"
    ),
    (
        "websitedraftgenerationrun",
        "ck_websitedraftgenerationrun_duration",
    ): "duration_ms IS NULL OR duration_ms >= 0",
    (
        "websitedraftgenerationitem",
        "ck_websitedraftgenerationitem_counts",
    ): "ordinal >= 1 AND attempt_count >= 0",
    (
        "websiteservicecoveragedecision",
        "ck_websiteservicecoveragedecision_status",
    ): "status IN ('included','excluded','deferred')",
    (
        "websiteservicecoveragedecision",
        "ck_websiteservicecoveragedecision_version",
    ): "decision_version >= 1",
    (
        "websitecountycoveragedecision",
        "ck_websitecountycoveragedecision_status",
    ): "status IN ('included','excluded','deferred')",
    (
        "websitecountycoveragedecision",
        "ck_websitecountycoveragedecision_version",
    ): "decision_version >= 1",
    (
        "websitecitycoveragedecision",
        "ck_websitecitycoveragedecision_status",
    ): "status IN ('included','excluded','deferred')",
    (
        "websitecitycoveragedecision",
        "ck_websitecitycoveragedecision_version",
    ): "decision_version >= 1",
    (
        "websiteservicecitycoveragedecision",
        "ck_websiteservicecitycoveragedecision_status",
    ): "status IN ('included','excluded','deferred')",
    (
        "websiteservicecitycoveragedecision",
        "ck_websiteservicecitycoveragedecision_version",
    ): "decision_version >= 1",
}

DISPOSITION_CHECK = (
    "draftingeligibilitydisposition",
    "ck_draftingeligibilitydisposition_decision",
)
CANONICAL_DISPOSITION_EXPRESSION = (
    "decision IN ('accepted','exception_approved','deferred','consolidate')"
)
ACTIVE_DISPOSITION_EXPRESSION = (
    "decision IN ('accepted','exception_approved','blocked','consolidate')"
)


@dataclass(frozen=True)
class ColumnContract:
    type_name: str
    nullable: bool
    default: str | None


@dataclass(frozen=True)
class IndexContract:
    table: str
    key_columns: tuple[str, ...]
    included_columns: tuple[str, ...] = ()
    unique: bool = False
    primary: bool = False
    access_method: str = "btree"
    predicate: str | None = None
    expression: str | None = None
    default_operator_classes: tuple[bool, ...] = (True,)
    options: tuple[int, ...] = (0,)
    valid: bool = True
    ready: bool = True


RELEVANT_INDEXES: dict[str, IndexContract] = {
    "ix_draftingeligibilitydisposition_accepted_exception": IndexContract(
        "draftingeligibilitydisposition", ("accepted_exception",)
    ),
    "ix_wordpressbootstrapcleanupaudit_action_type": IndexContract(
        "wordpressbootstrapcleanupaudit", ("action_type",)
    ),
    "ix_wordpresspluginupgradeaudit_action_type": IndexContract(
        "wordpresspluginupgradeaudit", ("action_type",)
    ),
}


@dataclass(frozen=True)
class SequenceContract:
    owner_table: str
    owner_column: str
    type_name: str
    start: int
    increment: int
    minimum: int
    maximum: int
    cache: int
    cycle: bool
    dependency_type: str


@dataclass(frozen=True)
class RuntimeTableSignature:
    columns: tuple[tuple[str, str, bool, str | None], ...]
    primary_key: tuple[str | None, tuple[str, ...]]
    uniques: tuple[tuple[str, tuple[str, ...]], ...]
    foreign_keys: tuple[
        tuple[tuple[str, ...], str, tuple[str, ...], str, str, str], ...
    ]
    checks: tuple[tuple[str | None, str], ...]
    indexes: tuple[tuple[str, tuple[str, ...], bool, str | None], ...]


@dataclass(frozen=True)
class PostgresSurface:
    revision: str
    tables: frozenset[str]
    sequences: frozenset[str]
    object_counts: tuple[tuple[str, int], ...]
    columns: tuple[tuple[str, ColumnContract], ...]
    checks: tuple[tuple[tuple[str, str], str | None], ...]
    indexes: tuple[tuple[str, IndexContract | None], ...]
    runtime_tables: tuple[tuple[str, RuntimeTableSignature], ...]
    sequence_contracts: tuple[tuple[str, SequenceContract], ...]
    catalog_manifest_sha256: str


RUNTIME_COLUMN_CONTRACTS: dict[str, dict[str, tuple[str, bool]]] = {
    "wordpressmetadatastate": {
        "created_at": ("datetime", False),
        "updated_at": ("datetime", False),
        "id": ("integer", False),
        "generated_page_id": ("integer", False),
        "wordpress_post_id": ("integer", False),
        "schema_version": ("string", False),
        "status": ("string", False),
        "payload": ("json", True),
        "payload_hash": ("string", True),
        "wordpress_revision": ("string", True),
        "last_verified_at": ("datetime", True),
        "last_wordpress_metadata_sync_at": ("datetime", True),
    },
    "wordpressmetadatasyncaudit": {
        "id": ("integer", False),
        "generated_page_id": ("integer", False),
        "wordpress_post_id": ("integer", False),
        "action_type": ("string", False),
        "status": ("string", False),
        "attempted_at": ("datetime", False),
        "completed_at": ("datetime", True),
        "wordpress_site_url": ("string", False),
        "payload_hash": ("string", False),
        "payload_snapshot": ("json", False),
        "previous_snapshot": ("json", True),
        "returned_snapshot": ("json", True),
        "gate_results": ("json", False),
        "data_backup_file_name": ("string", False),
        "wordpress_backup_reference": ("string", False),
        "plugin_version": ("string", False),
        "error_message": ("string", True),
    },
    "wordpressqualityreview": {
        "created_at": ("datetime", False),
        "updated_at": ("datetime", False),
        "id": ("integer", False),
        "generated_page_id": ("integer", False),
        "review_status": ("string", False),
        "reviewer_notes": ("string", True),
        "reviewed_at": ("datetime", True),
        "reviewed_by": ("string", True),
    },
}

RUNTIME_PRIMARY_KEYS = {
    table: (f"{table}_pkey", ("id",)) for table in RUNTIME_TABLES
}
RUNTIME_UNIQUES = {
    "wordpressmetadatastate": {
        "uq_wordpressmetadatastate_generated_page_id": ("generated_page_id",),
    },
    "wordpressmetadatasyncaudit": {
        "uq_wordpressmetadatasyncaudit_page_time_hash": (
            "generated_page_id",
            "attempted_at",
            "payload_hash",
        ),
    },
    "wordpressqualityreview": {
        "uq_wordpressqualityreview_generated_page_id": ("generated_page_id",),
    },
}
RUNTIME_INDEXES = {
    "wordpressmetadatastate": {
        "ix_wordpressmetadatastate_generated_page_id": ("generated_page_id",),
        "ix_wordpressmetadatastate_payload_hash": ("payload_hash",),
        "ix_wordpressmetadatastate_status": ("status",),
        "ix_wordpressmetadatastate_wordpress_post_id": ("wordpress_post_id",),
    },
    "wordpressmetadatasyncaudit": {
        "ix_wordpressmetadatasyncaudit_action_type": ("action_type",),
        "ix_wordpressmetadatasyncaudit_attempted_at": ("attempted_at",),
        "ix_wordpressmetadatasyncaudit_generated_page_id": ("generated_page_id",),
        "ix_wordpressmetadatasyncaudit_payload_hash": ("payload_hash",),
        "ix_wordpressmetadatasyncaudit_status": ("status",),
        "ix_wordpressmetadatasyncaudit_wordpress_post_id": ("wordpress_post_id",),
    },
    "wordpressqualityreview": {
        "ix_wordpressqualityreview_generated_page_id": ("generated_page_id",),
        "ix_wordpressqualityreview_review_status": ("review_status",),
    },
}


def _split_key(key: str) -> tuple[str, str]:
    table, column = key.split(".", 1)
    return table, column


def _canonical_default(expression: str | None) -> str | None:
    if expression is None or not str(expression).strip():
        return None
    value = " ".join(str(expression).strip().split())
    value = re.sub(
        r"::(?:character varying|varchar|text|boolean|integer|double precision|numeric)",
        "",
        value,
        flags=re.IGNORECASE,
    )
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    return value


def _canonical_check(expression: str) -> str:
    # This is intentionally the same narrow PostgreSQL deparse normalization
    # accepted by revision 0041.  It protects literals/quoted identifiers and
    # normalizes only casts, outer parentheses, IN/ANY, and Boolean formatting.
    quoted: list[str] = []

    def protect(match: re.Match[str]) -> str:
        quoted.append(match.group(0))
        return f"__atlas_quoted_{len(quoted) - 1}__"

    normalized = re.sub(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`",
        protect,
        expression,
    )
    normalized = " ".join(normalized.lower().split())
    if normalized.startswith("check "):
        normalized = normalized[6:].strip()
    normalized = re.sub(
        r"::(?:character\s+varying|varchar|text|integer|bigint)(?:\[\])?",
        "",
        normalized,
    )
    # pg_get_expr can render an ARRAY literal item either as
    # 'value'::varchar or as ('value'::varchar)::text.  Once the accepted casts
    # are removed, the remaining parentheses around that one protected literal
    # are purely deparse shape, not Boolean grouping.
    normalized = re.sub(
        r"\(\s*(__atlas_quoted_\d+__)\s*\)",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"\(\s*([a-z_][a-z0-9_]*)\s*\)",
        r"\1",
        normalized,
    )
    normalized = re.sub(
        r"any\s*\(\s*\(\s*array\[([^\]]*)\]\s*\)\s*\)",
        r"any (array[\1])",
        normalized,
    )
    normalized = re.sub(
        r"all\s*\(\s*\(\s*array\[([^\]]*)\]\s*\)\s*\)",
        r"all (array[\1])",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*"
        r"\(\s*array\[([^\]]*)\]\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*(?:<>|!=)\s*all\s*"
        r"\(\s*array\[([^\]]*)\]\s*\)",
        r"\1 not in (\2)",
        normalized,
    )
    normalized = normalized.replace("<>", "!=")

    def strip_outer(value: str) -> str:
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            closes_at_end = False
            in_string = False
            for index, character in enumerate(value):
                if character == "'":
                    in_string = not in_string
                elif not in_string and character == "(":
                    depth += 1
                elif not in_string and character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(value) - 1
                        break
            if not closes_at_end:
                break
            value = value[1:-1].strip()
        return value

    def split_top_level(value: str, operator: str) -> list[str]:
        token = f" {operator} "
        depth = 0
        start = 0
        index = 0
        in_string = False
        parts: list[str] = []
        while index < len(value):
            character = value[index]
            if character == "'":
                in_string = not in_string
            elif not in_string and character == "(":
                depth += 1
            elif not in_string and character == ")":
                depth -= 1
            elif not in_string and depth == 0 and value.startswith(token, index):
                parts.append(value[start:index].strip())
                index += len(token)
                start = index
                continue
            index += 1
        if parts:
            parts.append(value[start:].strip())
        return parts or [value]

    def canonical_boolean(value: str) -> str:
        value = strip_outer(value.strip())
        for operator in ("or", "and"):
            parts = split_top_level(value, operator)
            if len(parts) > 1:
                return f"{operator}(" + ",".join(
                    canonical_boolean(part) for part in parts
                ) + ")"
        return "".join(strip_outer(value).split())

    canonical = canonical_boolean(normalized)
    for index, value in enumerate(quoted):
        canonical = canonical.replace(f"__atlas_quoted_{index}__", value)
    return canonical


def _canonical_manifest_expression(expression: str) -> str:
    """Normalize only exact PG16 textual-membership deparse atoms.

    Recognized atoms may be nested in a larger Boolean CHECK.  Every cast and
    expression outside those atoms remains in the manifest.  In particular,
    removing an integer-width cast can change overflow and operator behavior.
    """

    raw = str(expression)
    quoted: list[str] = []
    sentinel_prefix = "__atlas_manifest_quoted_"
    while sentinel_prefix in raw.lower():
        sentinel_prefix = "_" + sentinel_prefix

    def protect(match: re.Match[str]) -> str:
        quoted.append(match.group(0))
        return f"{sentinel_prefix}{len(quoted) - 1}__"

    normalized = re.sub(
        r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`",
        protect,
        raw,
    )
    normalized = " ".join(normalized.lower().split())

    token = re.escape(sentinel_prefix) + r"\d+__"
    textual_type = r"(?:text|varchar|character\s+varying)"
    whole_item = rf"{token}\s*::\s*{textual_type}"
    whole_items = rf"{whole_item}(?:\s*,\s*{whole_item})*"
    per_item = (
        rf"\(\s*{token}\s*::\s*{textual_type}\s*\)\s*::\s*text"
    )
    per_items = rf"{per_item}(?:\s*,\s*{per_item})*"
    atom_prefix = (
        r"\(\(\s*(?P<column>[a-z_][a-z0-9_]*)\s*\)\s*::\s*text\s*"
        r"(?P<operator>=\s*any|(?:<>|!=)\s*all)\s*"
    )
    whole_array_pattern = re.compile(
        atom_prefix
        + rf"\(\s*\(\s*array\[(?P<items>{whole_items})\]\s*\)\s*::\s*"
        + rf"{textual_type}\s*\[\s*\]\s*\)\s*\)"
    )
    per_item_pattern = re.compile(
        atom_prefix
        + rf"\(\s*array\[(?P<items>{per_items})\]\s*\)\s*\)"
    )

    replacements = 0

    def replace_membership(match: re.Match[str]) -> str:
        nonlocal replacements
        indices = tuple(
            int(value)
            for value in re.findall(
                re.escape(sentinel_prefix) + r"(\d+)__",
                match.group("items"),
            )
        )
        if not indices or any(
            index >= len(quoted) or not quoted[index].startswith("'")
            for index in indices
        ):
            return match.group(0)
        replacements += 1
        operator = (
            "not_in"
            if match.group("operator").replace(" ", "") in {"<>all", "!=all"}
            else "in"
        )
        literal_payload = json.dumps(
            [quoted[index] for index in indices],
            ensure_ascii=True,
            separators=(",", ":"),
        ).encode("utf-8").hex()
        # NUL is forbidden in PostgreSQL text values and deparsed SQL.  The
        # structural marker therefore cannot collide with an unknown raw
        # function call or identifier that merely resembles the serializer.
        return (
            "\x00atlas_membership:"
            + match.group("column")
            + ":"
            + operator
            + ":"
            + literal_payload
            + "\x00"
        )

    normalized = whole_array_pattern.sub(replace_membership, normalized)
    normalized = per_item_pattern.sub(replace_membership, normalized)
    if replacements == 0:
        return raw

    def strip_outer(value: str) -> str:
        value = value.strip()
        while value.startswith("(") and value.endswith(")"):
            depth = 0
            closes_at_end = False
            for index, character in enumerate(value):
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(value) - 1
                        break
            if not closes_at_end:
                break
            value = value[1:-1].strip()
        return value

    def split_top_level(value: str, operator: str) -> list[str]:
        separator = f" {operator} "
        depth = 0
        start = 0
        index = 0
        parts: list[str] = []
        while index < len(value):
            character = value[index]
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(separator, index):
                parts.append(value[start:index].strip())
                index += len(separator)
                start = index
                continue
            index += 1
        if parts:
            parts.append(value[start:].strip())
        return parts or [value]

    def canonical_boolean(value: str) -> str:
        value = strip_outer(value)
        for operator in ("or", "and"):
            parts = split_top_level(value, operator)
            if len(parts) > 1:
                return f"{operator}(" + ",".join(
                    canonical_boolean(part) for part in parts
                ) + ")"
        # ``normalized`` already has exactly one whitespace character between
        # tokens outside protected literals.  Retain those token boundaries:
        # collapsing them would make ``flag IS NULL`` collide with a distinct
        # identifier such as ``flagisnull`` after one valid membership atom.
        return strip_outer(value)

    canonical = canonical_boolean(normalized)
    for index, value in enumerate(quoted):
        canonical = canonical.replace(f"{sentinel_prefix}{index}__", value)
    return canonical


def _target_column_contracts(variant: SourceVariant) -> dict[str, ColumnContract]:
    canonical = variant in {"clean", "canonical"}
    contracts = {
        key: ColumnContract(
            "timestamp with time zone" if canonical else "timestamp without time zone",
            False,
            None,
        )
        for key in TIMESTAMPTZ_COLUMNS
    }
    for key, default in SERVER_DEFAULTS.items():
        contracts[key] = ColumnContract(
            default.type_name,
            False,
            _canonical_default(default.sql) if canonical else None,
        )
    contracts.update(
        {
            "draftingeligibilityassessment.status": ColumnContract(
                "character varying" if canonical else "character varying(64)",
                False,
                None,
            ),
            "draftingeligibilitydisposition.decision": ColumnContract(
                "character varying" if canonical else "character varying(32)",
                False,
                None,
            ),
            "wordpressdeploymentaudit.partial_failure_details": ColumnContract(
                "character varying" if variant in {"active", "canonical"} else "text",
                True,
                None,
            ),
        }
    )
    if len(contracts) != 52:
        raise AssertionError("0046 must classify exactly 52 column differences.")
    return contracts


def _target_checks(variant: SourceVariant) -> dict[tuple[str, str], str | None]:
    canonical = variant in {"clean", "canonical"}
    checks: dict[tuple[str, str], str | None] = {
        key: _canonical_check(expression) if canonical else None
        for key, expression in CHECKS_TO_ADD.items()
    }
    checks[DISPOSITION_CHECK] = _canonical_check(
        CANONICAL_DISPOSITION_EXPRESSION if canonical else ACTIVE_DISPOSITION_EXPRESSION
    )
    return checks


def _target_indexes(variant: SourceVariant) -> dict[str, IndexContract | None]:
    if variant == "clean":
        return {name: None for name in RELEVANT_INDEXES}
    if variant == "active":
        return dict(RELEVANT_INDEXES)
    return {
        name: (
            None
            if name == "ix_draftingeligibilitydisposition_accepted_exception"
            else contract
        )
        for name, contract in RELEVANT_INDEXES.items()
    }


def _expected_sequence_contracts(variant: SourceVariant) -> dict[str, SequenceContract]:
    sequences = CLEAN_SEQUENCES if variant == "clean" else ACTIVE_SEQUENCES
    return {
        name: SequenceContract(
            owner_table=name.removesuffix("_id_seq"),
            owner_column="id",
            type_name="integer",
            start=1,
            increment=1,
            minimum=1,
            maximum=2147483647,
            cache=1,
            cycle=False,
            dependency_type="a",
        )
        for name in sequences
    }


def _expected_runtime_signature(table: str, *, postgresql: bool) -> RuntimeTableSignature:
    columns = tuple(
        sorted(
            (
                name,
                type_name,
                nullable,
                (
                    f"sequence:{table}_id_seq"
                    if postgresql and name == "id"
                    else None
                ),
            )
            for name, (type_name, nullable) in RUNTIME_COLUMN_CONTRACTS[table].items()
        )
    )
    primary_name = RUNTIME_PRIMARY_KEYS[table][0] if postgresql else None
    return RuntimeTableSignature(
        columns=columns,
        primary_key=(primary_name, ("id",)),
        uniques=tuple(sorted(RUNTIME_UNIQUES[table].items())),
        foreign_keys=((
            ("generated_page_id",),
            "generatedpage",
            ("id",),
            "NO ACTION",
            "NO ACTION",
            "NONE",
        ),),
        checks=(),
        indexes=tuple(
            sorted(
                (name, columns, False, None)
                for name, columns in RUNTIME_INDEXES[table].items()
            )
        ),
    )


def _expected_postgres_surface(variant: SourceVariant) -> PostgresSurface:
    if variant == "clean":
        tables = CLEAN_TABLES
        sequences = CLEAN_SEQUENCES
        counts = {
            "columns": 1182,
            "constraint:c": 150,
            "constraint:f": 174,
            "constraint:p": 62,
            "constraint:u": 71,
            "indexes": 563,
            "views": 0,
            "enums": 0,
            "user_triggers": 0,
        }
        runtime: dict[str, RuntimeTableSignature] = {}
    elif variant == "active":
        tables = ACTIVE_TABLES
        sequences = ACTIVE_SEQUENCES
        counts = {
            "columns": 1219,
            "constraint:c": 132,
            "constraint:f": 177,
            "constraint:p": 65,
            "constraint:u": 74,
            "indexes": 584,
            "views": 0,
            "enums": 0,
            "user_triggers": 0,
        }
        runtime = {
            table: _expected_runtime_signature(table, postgresql=True)
            for table in RUNTIME_TABLES
        }
    else:
        tables = ACTIVE_TABLES
        sequences = ACTIVE_SEQUENCES
        counts = {
            "columns": 1219,
            "constraint:c": 150,
            "constraint:f": 177,
            "constraint:p": 65,
            "constraint:u": 74,
            "indexes": 583,
            "views": 0,
            "enums": 0,
            "user_triggers": 0,
        }
        runtime = {
            table: _expected_runtime_signature(table, postgresql=True)
            for table in RUNTIME_TABLES
        }
    return PostgresSurface(
        revision="20260813_0045" if variant != "canonical" else revision,
        tables=tables,
        sequences=sequences,
        object_counts=tuple(sorted(counts.items())),
        columns=tuple(sorted(_target_column_contracts(variant).items())),
        checks=tuple(sorted(_target_checks(variant).items())),
        indexes=tuple(sorted(_target_indexes(variant).items())),
        runtime_tables=tuple(sorted(runtime.items())),
        sequence_contracts=tuple(
            sorted(_expected_sequence_contracts(variant).items())
        ),
        catalog_manifest_sha256=EXPECTED_CATALOG_MANIFEST_SHA256[variant],
    )


def _type_token(type_: sa.types.TypeEngine[Any]) -> str:
    if isinstance(type_, sa.Integer):
        return "integer"
    if isinstance(type_, sa.DateTime):
        return "datetime_tz" if bool(getattr(type_, "timezone", False)) else "datetime"
    if isinstance(type_, sa.JSON):
        return "json"
    if isinstance(type_, sa.String) and not isinstance(type_, sa.Text):
        return "string"
    if isinstance(type_, sa.Text):
        return "text"
    return str(type_).lower()


def _runtime_table_signature(bind: Any, table: str) -> RuntimeTableSignature:
    inspector = sa.inspect(bind)
    dialect = bind.dialect.name
    columns: list[tuple[str, str, bool, str | None]] = []
    for item in inspector.get_columns(table):
        default = _canonical_default(item.get("default"))
        if dialect == "postgresql" and item["name"] == "id":
            expected = f"nextval('{table}_id_seq'::regclass)"
            if default != expected:
                default_token = default
            else:
                default_token = f"sequence:{table}_id_seq"
        else:
            default_token = default
        columns.append(
            (
                str(item["name"]),
                _type_token(item["type"]),
                bool(item.get("nullable")),
                default_token,
            )
        )

    primary = inspector.get_pk_constraint(table)
    primary_name = primary.get("name") if dialect == "postgresql" else None
    uniques = tuple(
        sorted(
            (
                str(item.get("name")),
                tuple(item.get("column_names") or ()),
            )
            for item in inspector.get_unique_constraints(table)
            if item.get("name")
        )
    )
    foreign_keys = []
    for item in inspector.get_foreign_keys(table):
        options = item.get("options") or {}
        foreign_keys.append(
            (
                tuple(item.get("constrained_columns") or ()),
                str(item.get("referred_table") or ""),
                tuple(item.get("referred_columns") or ()),
                str(options.get("onupdate", "NO ACTION")).upper(),
                str(options.get("ondelete", "NO ACTION")).upper(),
                str(options.get("match", "NONE")).upper(),
            )
        )
    checks = tuple(
        sorted(
            (
                item.get("name"),
                _canonical_check(item.get("sqltext") or ""),
            )
            for item in inspector.get_check_constraints(table)
        )
    )
    indexes = tuple(
        sorted(
            (
                str(item.get("name")),
                tuple(item.get("column_names") or ()),
                bool(item.get("unique")),
                _canonical_check(
                    str((item.get("dialect_options") or {}).get("postgresql_where"))
                )
                if (item.get("dialect_options") or {}).get("postgresql_where")
                else None,
            )
            for item in inspector.get_indexes(table)
            if item.get("name") and not item.get("duplicates_constraint")
        )
    )
    return RuntimeTableSignature(
        columns=tuple(sorted(columns)),
        primary_key=(primary_name, tuple(primary.get("constrained_columns") or ())),
        uniques=uniques,
        foreign_keys=tuple(sorted(foreign_keys)),
        checks=checks,
        indexes=indexes,
    )


def _read_postgres_index(bind: Any, name: str) -> IndexContract | None:
    row = bind.execute(
        sa.text(
            """
            SELECT table_relation.relname,
                   access_method.amname,
                   index_record.indisunique,
                   index_record.indisprimary,
                   index_record.indisvalid,
                   index_record.indisready,
                   index_record.indnkeyatts,
                   index_record.indnatts,
                   pg_get_expr(index_record.indpred, index_record.indrelid, true)
                       AS predicate,
                   pg_get_expr(index_record.indexprs, index_record.indrelid, true)
                       AS expression,
                   ARRAY(
                       SELECT attribute.attname
                       FROM generate_series(0, index_record.indnatts - 1) slot
                       LEFT JOIN pg_attribute AS attribute
                         ON attribute.attrelid = index_record.indrelid
                        AND attribute.attnum = index_record.indkey[slot]
                       ORDER BY slot
                   ) AS attribute_names,
                   ARRAY(
                       SELECT operator_class.opcdefault
                       FROM generate_series(0, index_record.indnkeyatts - 1) slot
                       JOIN pg_opclass AS operator_class
                         ON operator_class.oid = index_record.indclass[slot]
                       ORDER BY slot
                   ) AS default_operator_classes,
                   ARRAY(
                       SELECT index_record.indoption[slot]
                       FROM generate_series(0, index_record.indnkeyatts - 1) slot
                       ORDER BY slot
                   ) AS index_options
            FROM pg_index AS index_record
            JOIN pg_class AS index_relation
              ON index_relation.oid = index_record.indexrelid
            JOIN pg_class AS table_relation
              ON table_relation.oid = index_record.indrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = table_relation.relnamespace
            JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
            WHERE namespace.nspname = 'public'
              AND index_relation.relname = :name
            """
        ),
        {"name": name},
    ).mappings().one_or_none()
    if row is None:
        return None
    columns = tuple(str(value) for value in row["attribute_names"])
    key_count = int(row["indnkeyatts"])
    return IndexContract(
        table=str(row["relname"]),
        key_columns=columns[:key_count],
        included_columns=columns[key_count:],
        unique=bool(row["indisunique"]),
        primary=bool(row["indisprimary"]),
        access_method=str(row["amname"]),
        predicate=(
            _canonical_check(str(row["predicate"]))
            if row["predicate"] is not None
            else None
        ),
        expression=(
            _canonical_check(str(row["expression"]))
            if row["expression"] is not None
            else None
        ),
        default_operator_classes=tuple(bool(v) for v in row["default_operator_classes"]),
        options=tuple(int(v) for v in row["index_options"]),
        valid=bool(row["indisvalid"]),
        ready=bool(row["indisready"]),
    )


def _stable_text(value: Any) -> str | None:
    if value is None:
        return None
    # PostgreSQL 16 deparsing is deterministic.  Preserve the exact text so
    # whitespace inside quoted literals remains semantic (for example, 'a  b'
    # must never collide with 'a b').
    return str(value)


def _stable_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_stable_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _stable_value(item) for key, item in sorted(value.items())}
    return str(value)


def _count_pairs(result: Any) -> dict[str, int]:
    return {str(kind): int(count) for kind, count in result.all()}


def _catalog_records_sha256(records: list[dict[str, Any]]) -> str:
    """Serialize semantic records, omitting only physical column ordinals."""

    serialized = [
        json.dumps(
            {"kind": "manifest", "version": CATALOG_MANIFEST_VERSION},
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    ]
    for record in records:
        semantic_record = {
            key: value
            for key, value in record.items()
            if key not in {"attnum", "ordinal_position"}
        }
        serialized.append(
            json.dumps(
                _stable_value(semantic_record),
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    payload = "\n".join(sorted(serialized)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_frozen_catalog_manifest_digests() -> None:
    pending = [
        variant
        for variant, digest in EXPECTED_CATALOG_MANIFEST_SHA256.items()
        if variant in {"clean", "active"}
        if re.fullmatch(r"[0-9a-f]{64}", digest) is None
    ]
    if pending:
        raise RuntimeError(
            "Revision 0046 PostgreSQL catalog manifests are not frozen for: "
            + ", ".join(sorted(pending))
            + ". Refusing upgrade before catalog inspection or mutation."
        )


def _require_supported_postgresql_major(bind: Any) -> None:
    server_version_num = int(
        bind.exec_driver_sql("SHOW server_version_num").scalar_one()
    )
    major = server_version_num // 10000
    if major != SUPPORTED_POSTGRESQL_MAJOR:
        raise RuntimeError(
            "Revision 0046 catalog digests require PostgreSQL "
            f"{SUPPORTED_POSTGRESQL_MAJOR}; observed major {major}. "
            "No catalog classification or mutation was attempted."
        )


def _foreign_key_manifest_name(
    *,
    table: str,
    name: str,
    local_columns: tuple[str, ...],
    referred_table: str,
    referred_columns: tuple[str, ...],
) -> str:
    key = (table, local_columns, referred_table, referred_columns)
    aliases = FK_NAME_ALIASES.get(key)
    if aliases is None:
        return name
    if name not in aliases:
        raise RuntimeError(
            "Revision 0046 found an unknown foreign-key name for an accepted "
            f"alias key: {table}.{','.join(local_columns)} -> "
            f"{referred_table}.{','.join(referred_columns)} ({name})."
        )
    return "accepted-fk-alias:" + table + ":" + ",".join(local_columns)


def _catalog_manifest_sha256(bind: Any) -> str:
    """Hash every PostgreSQL schema semantic not classified separately.

    The physical normalizations are omission of column ordinal positions and
    substitution of the sixteen documented foreign-key name aliases.  CHECK
    expressions and partial-index predicates normalize only the two exact PG16
    textual-membership deparse aliases; arbitrary expressions remain raw.  The
    52 columns, 19 checks, and 3 indexes in the readable surface are also hashed
    here in full; the duplicate representation keeps mismatch diagnostics
    useful to an operator.
    """

    records: list[dict[str, Any]] = []
    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname,
                   relation.relkind,
                   relation.relpersistence,
                   relation.relrowsecurity,
                   relation.relforcerowsecurity,
                   relation.relispartition,
                   relation.relreplident,
                   relation.reloptions,
                   table_access_method.amname AS table_access_method,
                   tablespace.spcname AS tablespace_name,
                   parent_relation.relname AS partition_parent,
                   pg_get_expr(relation.relpartbound, relation.oid, false)
                       AS partition_bound
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_am AS table_access_method
              ON table_access_method.oid = relation.relam
            LEFT JOIN pg_tablespace AS tablespace
              ON tablespace.oid = relation.reltablespace
            LEFT JOIN pg_inherits AS inheritance
              ON inheritance.inhrelid = relation.oid
            LEFT JOIN pg_class AS parent_relation
              ON parent_relation.oid = inheritance.inhparent
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
            ORDER BY relation.relname
            """
        )
    ).mappings():
        records.append(
            {
                "kind": "table",
                "name": row["relname"],
                "relation_kind": row["relkind"],
                "persistence": row["relpersistence"],
                "row_security": row["relrowsecurity"],
                "force_row_security": row["relforcerowsecurity"],
                "is_partition": row["relispartition"],
                "replica_identity": row["relreplident"],
                "options": _stable_value(row["reloptions"]),
                "access_method": row["table_access_method"],
                "tablespace": row["tablespace_name"],
                "partition_parent": row["partition_parent"],
                "partition_bound": _stable_text(row["partition_bound"]),
            }
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT columns.table_name,
                   columns.column_name,
                   columns.data_type,
                   columns.udt_schema,
                   columns.udt_name,
                   columns.domain_schema,
                   columns.domain_name,
                   columns.is_nullable,
                   columns.column_default,
                   columns.character_maximum_length,
                   columns.character_octet_length,
                   columns.numeric_precision,
                   columns.numeric_precision_radix,
                   columns.numeric_scale,
                   columns.datetime_precision,
                   columns.interval_type,
                   columns.interval_precision,
                   columns.collation_schema,
                   columns.collation_name,
                   columns.is_identity,
                   columns.identity_generation,
                   columns.identity_start,
                   columns.identity_increment,
                   columns.identity_maximum,
                   columns.identity_minimum,
                   columns.identity_cycle,
                   columns.is_generated,
                   columns.generation_expression,
                   attribute.attstorage::text AS storage_strategy,
                   attribute.attcompression::text AS compression_method,
                   attribute.attstattarget AS statistics_target,
                   attribute.attislocal AS is_local,
                   attribute.attinhcount AS inheritance_count
            FROM information_schema.columns AS columns
            JOIN pg_namespace AS namespace
              ON namespace.nspname = columns.table_schema
            JOIN pg_class AS relation
              ON relation.relnamespace = namespace.oid
             AND relation.relname = columns.table_name
            JOIN pg_attribute AS attribute
              ON attribute.attrelid = relation.oid
             AND attribute.attname = columns.column_name
            WHERE columns.table_schema = 'public'
            ORDER BY columns.table_name, columns.column_name
            """
        )
    ).mappings():
        records.append(
            {
                "kind": "column",
                **{name: _stable_text(row[name]) for name in row},
            }
        )

    constraint_rows = bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   constraint_record.conname AS constraint_name,
                   constraint_record.contype::text AS constraint_type,
                   constraint_record.condeferrable,
                   constraint_record.condeferred,
                   constraint_record.convalidated,
                   constraint_record.conislocal,
                   constraint_record.coninhcount,
                   constraint_record.connoinherit,
                   constraint_record.confmatchtype::text AS match_type,
                   constraint_record.confupdtype::text AS update_type,
                   constraint_record.confdeltype::text AS delete_type,
                   referred_namespace.nspname AS referred_schema,
                   referred_relation.relname AS referred_table,
                   ARRAY(
                       SELECT attribute.attname
                       FROM unnest(constraint_record.conkey)
                            WITH ORDINALITY AS key(attnum, ordinal)
                       JOIN pg_attribute AS attribute
                         ON attribute.attrelid = constraint_record.conrelid
                        AND attribute.attnum = key.attnum
                       ORDER BY key.ordinal
                   ) AS local_columns,
                   ARRAY(
                       SELECT attribute.attname
                       FROM unnest(constraint_record.confkey)
                            WITH ORDINALITY AS key(attnum, ordinal)
                       JOIN pg_attribute AS attribute
                         ON attribute.attrelid = constraint_record.confrelid
                        AND attribute.attnum = key.attnum
                       ORDER BY key.ordinal
                   ) AS referred_columns,
                   CASE WHEN constraint_record.contype = 'c'
                        THEN pg_get_expr(
                            constraint_record.conbin,
                            constraint_record.conrelid,
                            false
                        )
                        ELSE NULL
                   END AS check_expression,
                   CASE WHEN constraint_record.contype NOT IN ('c', 'f', 'p', 'u')
                        THEN pg_get_constraintdef(constraint_record.oid, false)
                        ELSE NULL
                   END AS other_definition
            FROM pg_constraint AS constraint_record
            JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            LEFT JOIN pg_class AS referred_relation
              ON referred_relation.oid = constraint_record.confrelid
            LEFT JOIN pg_namespace AS referred_namespace
              ON referred_namespace.oid = referred_relation.relnamespace
            WHERE namespace.nspname = 'public'
            ORDER BY relation.relname,
                     constraint_record.contype,
                     constraint_record.conname
            """
        )
    ).mappings()
    for row in constraint_rows:
        table = str(row["table_name"])
        name = str(row["constraint_name"])
        constraint_type = str(row["constraint_type"])
        local_columns = tuple(str(value) for value in (row["local_columns"] or ()))
        referred_columns = tuple(
            str(value) for value in (row["referred_columns"] or ())
        )
        referred_table = str(row["referred_table"] or "")
        if constraint_type == "f":
            name = _foreign_key_manifest_name(
                table=table,
                name=name,
                local_columns=local_columns,
                referred_table=referred_table,
                referred_columns=referred_columns,
            )
        records.append(
            {
                "kind": "constraint",
                "table": table,
                "name": name,
                "constraint_type": constraint_type,
                "local_columns": local_columns,
                "referred_schema": row["referred_schema"],
                "referred_table": referred_table or None,
                "referred_columns": referred_columns,
                "match_type": row["match_type"],
                "update_type": row["update_type"],
                "delete_type": row["delete_type"],
                "deferrable": row["condeferrable"],
                "initially_deferred": row["condeferred"],
                "validated": row["convalidated"],
                "is_local": row["conislocal"],
                "inheritance_count": row["coninhcount"],
                "no_inherit": row["connoinherit"],
                "check_expression": (
                    _canonical_manifest_expression(str(row["check_expression"]))
                    if row["check_expression"] is not None
                    else None
                ),
                "other_definition": _stable_text(row["other_definition"]),
            }
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT table_relation.relname AS table_name,
                   index_relation.relname AS index_name,
                   access_method.amname AS access_method,
                   index_record.indisunique,
                   index_record.indisprimary,
                   index_record.indisexclusion,
                   index_record.indimmediate,
                   index_record.indisclustered,
                   index_record.indisvalid,
                   index_record.indisready,
                   index_record.indislive,
                   index_record.indisreplident,
                   index_record.indnullsnotdistinct,
                   index_record.indnkeyatts,
                   index_record.indnatts,
                   index_relation.relpersistence AS index_persistence,
                   index_relation.reloptions AS index_options,
                   tablespace.spcname AS index_tablespace,
                   pg_get_expr(index_record.indpred, index_record.indrelid, false)
                       AS predicate,
                   ARRAY(
                       SELECT pg_get_indexdef(
                           index_record.indexrelid,
                           slot,
                           false
                       )
                       FROM generate_series(1, index_record.indnatts) AS slot
                       ORDER BY slot
                   ) AS attribute_definitions,
                   ARRAY(
                       SELECT operator_namespace.nspname || '.' || operator_class.opcname
                       FROM generate_series(0, index_record.indnkeyatts - 1) AS slot
                       JOIN pg_opclass AS operator_class
                         ON operator_class.oid = index_record.indclass[slot]
                       JOIN pg_namespace AS operator_namespace
                         ON operator_namespace.oid = operator_class.opcnamespace
                       ORDER BY slot
                   ) AS operator_classes,
                   ARRAY(
                       SELECT operator_class.opcdefault
                       FROM generate_series(0, index_record.indnkeyatts - 1) AS slot
                       JOIN pg_opclass AS operator_class
                         ON operator_class.oid = index_record.indclass[slot]
                       ORDER BY slot
                   ) AS default_operator_classes,
                   ARRAY(
                       SELECT CASE WHEN index_record.indcollation[slot] = 0
                                   THEN NULL
                                   ELSE collation_namespace.nspname || '.' || collation_record.collname
                              END
                       FROM generate_series(0, index_record.indnkeyatts - 1) AS slot
                       LEFT JOIN pg_collation AS collation_record
                         ON collation_record.oid = index_record.indcollation[slot]
                       LEFT JOIN pg_namespace AS collation_namespace
                         ON collation_namespace.oid = collation_record.collnamespace
                       ORDER BY slot
                   ) AS collations,
                   ARRAY(
                       SELECT index_record.indoption[slot]
                       FROM generate_series(0, index_record.indnkeyatts - 1) AS slot
                       ORDER BY slot
                   ) AS options
            FROM pg_index AS index_record
            JOIN pg_class AS index_relation
              ON index_relation.oid = index_record.indexrelid
            JOIN pg_class AS table_relation
              ON table_relation.oid = index_record.indrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = table_relation.relnamespace
            JOIN pg_am AS access_method ON access_method.oid = index_relation.relam
            LEFT JOIN pg_tablespace AS tablespace
              ON tablespace.oid = index_relation.reltablespace
            WHERE namespace.nspname = 'public'
            ORDER BY table_relation.relname, index_relation.relname
            """
        )
    ).mappings():
        records.append(
            {
                "kind": "index",
                **{
                    name: _stable_value(row[name])
                    for name in row
                    if name != "predicate"
                },
                "predicate": (
                    _canonical_manifest_expression(str(row["predicate"]))
                    if row["predicate"] is not None
                    else None
                ),
            }
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT sequence_relation.relname AS sequence_name,
                   sequence_relation.relpersistence AS persistence,
                   sequence_relation.reloptions AS options,
                   tablespace.spcname AS tablespace_name,
                   pg_catalog.format_type(sequence_record.seqtypid, NULL) AS type_name,
                   sequence_record.seqstart,
                   sequence_record.seqincrement,
                   sequence_record.seqmin,
                   sequence_record.seqmax,
                   sequence_record.seqcache,
                   sequence_record.seqcycle,
                   owner_namespace.nspname AS owner_schema,
                   owner_relation.relname AS owner_table,
                   owner_attribute.attname AS owner_column,
                   dependency.deptype::text AS dependency_type
            FROM pg_sequence AS sequence_record
            JOIN pg_class AS sequence_relation
              ON sequence_relation.oid = sequence_record.seqrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = sequence_relation.relnamespace
            LEFT JOIN pg_tablespace AS tablespace
              ON tablespace.oid = sequence_relation.reltablespace
            LEFT JOIN pg_depend AS dependency
              ON dependency.classid = 'pg_class'::regclass
             AND dependency.objid = sequence_relation.oid
             AND dependency.objsubid = 0
             AND dependency.refclassid = 'pg_class'::regclass
             AND dependency.deptype IN ('a', 'i')
            LEFT JOIN pg_class AS owner_relation
              ON owner_relation.oid = dependency.refobjid
            LEFT JOIN pg_namespace AS owner_namespace
              ON owner_namespace.oid = owner_relation.relnamespace
            LEFT JOIN pg_attribute AS owner_attribute
              ON owner_attribute.attrelid = dependency.refobjid
             AND owner_attribute.attnum = dependency.refobjsubid
            WHERE namespace.nspname = 'public'
            ORDER BY sequence_relation.relname
            """
        )
    ).mappings():
        records.append(
            {"kind": "sequence", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT namespace.nspname
            FROM pg_namespace AS namespace
            WHERE namespace.nspname <> 'information_schema'
              AND namespace.nspname !~ '^pg_'
            ORDER BY namespace.nspname
            """
        )
    ).mappings():
        records.append(
            {"kind": "schema", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname,
                   relation.relkind,
                   relation.relpersistence,
                   pg_get_viewdef(relation.oid, false) AS definition
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('v', 'm')
            ORDER BY relation.relname
            """
        )
    ).mappings():
        records.append(
            {
                "kind": "view",
                **{name: _stable_text(row[name]) for name in row},
            }
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT type_record.typname,
                   type_record.typtype::text,
                   pg_catalog.format_type(type_record.typbasetype, type_record.typtypmod)
                       AS base_type,
                   type_record.typnotnull,
                   pg_get_expr(type_record.typdefaultbin, 0, false) AS default_expression,
                   ARRAY(
                       SELECT enum_record.enumlabel
                       FROM pg_enum AS enum_record
                       WHERE enum_record.enumtypid = type_record.oid
                       ORDER BY enum_record.enumsortorder
                   ) AS enum_labels,
                   ARRAY(
                       SELECT constraint_record.conname || ':' ||
                              pg_get_constraintdef(constraint_record.oid, false)
                       FROM pg_constraint AS constraint_record
                       WHERE constraint_record.contypid = type_record.oid
                       ORDER BY constraint_record.conname
                   ) AS domain_constraints
            FROM pg_type AS type_record
            JOIN pg_namespace AS namespace
              ON namespace.oid = type_record.typnamespace
            WHERE namespace.nspname = 'public'
              AND type_record.typtype IN ('d', 'e')
            ORDER BY type_record.typname
            """
        )
    ).mappings():
        records.append(
            {"kind": "type", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   trigger_record.tgname AS trigger_name,
                   trigger_record.tgenabled,
                   pg_get_triggerdef(trigger_record.oid, false) AS definition
            FROM pg_trigger AS trigger_record
            JOIN pg_class AS relation ON relation.oid = trigger_record.tgrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND NOT trigger_record.tgisinternal
            ORDER BY relation.relname, trigger_record.tgname
            """
        )
    ).mappings():
        records.append(
            {
                "kind": "trigger",
                **{name: _stable_text(row[name]) for name in row},
            }
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT extension.extname,
                   extension.extversion,
                   namespace.nspname,
                   extension.extrelocatable
            FROM pg_extension AS extension
            JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
            ORDER BY extension.extname
            """
        )
    ).mappings():
        records.append(
            {"kind": "extension", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   policy.polname,
                   policy.polpermissive,
                   policy.polcmd,
                   ARRAY(
                       SELECT COALESCE(role_record.rolname, 'PUBLIC')
                       FROM unnest(policy.polroles) AS role(role_oid)
                       LEFT JOIN pg_roles AS role_record
                         ON role_record.oid = role.role_oid
                       ORDER BY COALESCE(role_record.rolname, 'PUBLIC')
                   ) AS roles,
                   pg_get_expr(policy.polqual, policy.polrelid, false) AS using_expression,
                   pg_get_expr(policy.polwithcheck, policy.polrelid, false)
                       AS check_expression
            FROM pg_policy AS policy
            JOIN pg_class AS relation ON relation.oid = policy.polrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
            ORDER BY relation.relname, policy.polname
            """
        )
    ).mappings():
        records.append(
            {"kind": "policy", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT namespace.nspname AS schema_name,
                   procedure_record.proname,
                   procedure_record.prokind::text,
                   pg_get_function_identity_arguments(procedure_record.oid)
                       AS identity_arguments,
                   pg_get_function_result(procedure_record.oid) AS result_type,
                   language_record.lanname AS language_name,
                   procedure_record.provolatile::text AS volatility,
                   procedure_record.proparallel::text AS parallel_safety,
                   procedure_record.prosecdef AS security_definer,
                   procedure_record.proleakproof AS leakproof,
                   procedure_record.proisstrict AS strict,
                   procedure_record.procost AS estimated_cost,
                   procedure_record.prorows AS estimated_rows,
                   procedure_record.proconfig AS configuration,
                   pg_get_functiondef(procedure_record.oid) AS definition
            FROM pg_proc AS procedure_record
            JOIN pg_namespace AS namespace
              ON namespace.oid = procedure_record.pronamespace
            JOIN pg_language AS language_record
              ON language_record.oid = procedure_record.prolang
            WHERE namespace.nspname <> 'information_schema'
              AND namespace.nspname !~ '^pg_'
            ORDER BY namespace.nspname,
                     procedure_record.proname,
                     pg_get_function_identity_arguments(procedure_record.oid)
            """
        )
    ).mappings():
        records.append(
            {"kind": "routine", **{name: _stable_value(row[name]) for name in row}}
        )

    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   rewrite_record.rulename AS rule_name,
                   rewrite_record.ev_enabled AS enabled,
                   pg_get_ruledef(rewrite_record.oid, false) AS definition
            FROM pg_rewrite AS rewrite_record
            JOIN pg_class AS relation ON relation.oid = rewrite_record.ev_class
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND rewrite_record.rulename <> '_RETURN'
            ORDER BY relation.relname, rewrite_record.rulename
            """
        )
    ).mappings():
        records.append(
            {"kind": "rule", **{name: _stable_value(row[name]) for name in row}}
        )

    return _catalog_records_sha256(records)


def _read_postgres_surface(bind: Any, *, post_upgrade: bool = False) -> PostgresSurface:
    revision_value = bind.execute(
        sa.text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    if post_upgrade:
        # Alembic updates its version row after upgrade() returns.  The schema
        # validator still records the canonical destination identity.
        revision_value = revision

    tables = frozenset(
        str(value)
        for value in bind.execute(
            sa.text(
                """
                SELECT relation.relname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind IN ('r', 'p')
                """
            )
        ).scalars()
    )
    sequences = frozenset(
        str(value)
        for value in bind.execute(
            sa.text(
                """
                SELECT relation.relname
                FROM pg_class AS relation
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                  AND relation.relkind = 'S'
                """
            )
        ).scalars()
    )
    counts = {
        "columns": int(
            bind.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM pg_attribute AS attribute
                    JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relkind IN ('r', 'p')
                      AND attribute.attnum > 0
                      AND NOT attribute.attisdropped
                    """
                )
            ).scalar_one()
        ),
        "indexes": int(
            bind.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM pg_index AS index_record
                    JOIN pg_class AS relation ON relation.oid = index_record.indrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                    """
                )
            ).scalar_one()
        ),
        "views": int(
            bind.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM pg_class AS relation
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND relation.relkind IN ('v', 'm')
                    """
                )
            ).scalar_one()
        ),
        "enums": int(
            bind.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM pg_type AS type_record
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = type_record.typnamespace
                    WHERE namespace.nspname = 'public'
                      AND type_record.typtype = 'e'
                    """
                )
            ).scalar_one()
        ),
        "user_triggers": int(
            bind.execute(
                sa.text(
                    """
                    SELECT COUNT(*)
                    FROM pg_trigger AS trigger_record
                    JOIN pg_class AS relation ON relation.oid = trigger_record.tgrelid
                    JOIN pg_namespace AS namespace
                      ON namespace.oid = relation.relnamespace
                    WHERE namespace.nspname = 'public'
                      AND NOT trigger_record.tgisinternal
                    """
                )
            ).scalar_one()
        ),
    }
    constraint_counts = _count_pairs(
        bind.execute(
            sa.text(
                """
                SELECT constraint_record.contype::text, COUNT(*)
                FROM pg_constraint AS constraint_record
                JOIN pg_class AS relation
                  ON relation.oid = constraint_record.conrelid
                JOIN pg_namespace AS namespace
                  ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = 'public'
                GROUP BY constraint_record.contype
                """
            )
        )
    )
    for kind, count in constraint_counts.items():
        counts[f"constraint:{kind}"] = int(count)

    target_keys = set(_target_column_contracts("canonical"))
    observed_columns: dict[str, ColumnContract] = {}
    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   attribute.attname AS column_name,
                   pg_catalog.format_type(attribute.atttypid, attribute.atttypmod)
                       AS type_name,
                   NOT attribute.attnotnull AS nullable,
                   pg_get_expr(default_record.adbin, default_record.adrelid, true)
                       AS default_expression
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
            LEFT JOIN pg_attrdef AS default_record
              ON default_record.adrelid = relation.oid
             AND default_record.adnum = attribute.attnum
            WHERE namespace.nspname = 'public'
              AND relation.relkind IN ('r', 'p')
              AND attribute.attnum > 0
              AND NOT attribute.attisdropped
            """
        )
    ).mappings():
        key = f"{row['table_name']}.{row['column_name']}"
        if key in target_keys:
            observed_columns[key] = ColumnContract(
                str(row["type_name"]),
                bool(row["nullable"]),
                _canonical_default(row["default_expression"]),
            )

    target_check_keys = set(_target_checks("canonical"))
    observed_checks: dict[tuple[str, str], str | None] = {
        key: None for key in target_check_keys
    }
    for row in bind.execute(
        sa.text(
            """
            SELECT relation.relname AS table_name,
                   constraint_record.conname AS constraint_name,
                   pg_get_expr(
                       constraint_record.conbin,
                       constraint_record.conrelid,
                       true
                   ) AS expression
            FROM pg_constraint AS constraint_record
            JOIN pg_class AS relation ON relation.oid = constraint_record.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public'
              AND constraint_record.contype = 'c'
            """
        )
    ).mappings():
        key = (str(row["table_name"]), str(row["constraint_name"]))
        if key in target_check_keys:
            observed_checks[key] = _canonical_check(str(row["expression"]))

    observed_indexes = {
        name: _read_postgres_index(bind, name) for name in RELEVANT_INDEXES
    }
    runtime = {
        table: _runtime_table_signature(bind, table)
        for table in RUNTIME_TABLES
        if table in tables
    }

    sequence_contracts: dict[str, SequenceContract] = {}
    for row in bind.execute(
        sa.text(
            """
            SELECT sequence_relation.relname AS sequence_name,
                   pg_catalog.format_type(sequence_record.seqtypid, NULL) AS type_name,
                   sequence_record.seqstart,
                   sequence_record.seqincrement,
                   sequence_record.seqmin,
                   sequence_record.seqmax,
                   sequence_record.seqcache,
                   sequence_record.seqcycle,
                   owner_relation.relname AS owner_table,
                   owner_attribute.attname AS owner_column,
                   dependency.deptype::text AS dependency_type
            FROM pg_sequence AS sequence_record
            JOIN pg_class AS sequence_relation
              ON sequence_relation.oid = sequence_record.seqrelid
            JOIN pg_namespace AS namespace
              ON namespace.oid = sequence_relation.relnamespace
            LEFT JOIN pg_depend AS dependency
              ON dependency.classid = 'pg_class'::regclass
             AND dependency.objid = sequence_relation.oid
             AND dependency.objsubid = 0
             AND dependency.refclassid = 'pg_class'::regclass
             AND dependency.deptype IN ('a', 'i')
            LEFT JOIN pg_class AS owner_relation
              ON owner_relation.oid = dependency.refobjid
            LEFT JOIN pg_attribute AS owner_attribute
              ON owner_attribute.attrelid = dependency.refobjid
             AND owner_attribute.attnum = dependency.refobjsubid
            WHERE namespace.nspname = 'public'
            """
        )
    ).mappings():
        sequence_contracts[str(row["sequence_name"])] = SequenceContract(
            owner_table=str(row["owner_table"] or ""),
            owner_column=str(row["owner_column"] or ""),
            type_name=str(row["type_name"]),
            start=int(row["seqstart"]),
            increment=int(row["seqincrement"]),
            minimum=int(row["seqmin"]),
            maximum=int(row["seqmax"]),
            cache=int(row["seqcache"]),
            cycle=bool(row["seqcycle"]),
            dependency_type=str(row["dependency_type"] or ""),
        )

    return PostgresSurface(
        revision=str(revision_value),
        tables=tables,
        sequences=sequences,
        object_counts=tuple(sorted(counts.items())),
        columns=tuple(sorted(observed_columns.items())),
        checks=tuple(sorted(observed_checks.items())),
        indexes=tuple(sorted(observed_indexes.items())),
        runtime_tables=tuple(sorted(runtime.items())),
        sequence_contracts=tuple(sorted(sequence_contracts.items())),
        catalog_manifest_sha256=_catalog_manifest_sha256(bind),
    )


def _surface_mismatches(
    observed: PostgresSurface, expected: PostgresSurface
) -> tuple[str, ...]:
    mismatches = []
    for field in PostgresSurface.__dataclass_fields__:
        if getattr(observed, field) != getattr(expected, field):
            mismatches.append(field)
    return tuple(mismatches)


def _classify_postgres_surface(surface: PostgresSurface) -> Literal["clean", "active"]:
    for variant in ("clean", "active"):
        if surface == _expected_postgres_surface(variant):
            return variant
    clean_diff = ", ".join(
        _surface_mismatches(surface, _expected_postgres_surface("clean"))
    )
    active_diff = ", ".join(
        _surface_mismatches(surface, _expected_postgres_surface("active"))
    )
    raise RuntimeError(
        "Revision 0046 rejected an unknown PostgreSQL 0045 schema before DDL. "
        f"Observed manifest {surface.catalog_manifest_sha256}; expected clean "
        f"{EXPECTED_CATALOG_MANIFEST_SHA256['clean']} or active "
        f"{EXPECTED_CATALOG_MANIFEST_SHA256['active']}. "
        f"Clean-shape differences: {clean_diff or 'none'}; "
        f"active-shape differences: {active_diff or 'none'}."
    )


def _preflight_canonical_data(bind: Any) -> None:
    for (table, name), expression in CHECKS_TO_ADD.items():
        violations = bind.execute(
            sa.text(f'SELECT COUNT(*) FROM "{table}" WHERE NOT ({expression})')
        ).scalar_one()
        if violations:
            raise RuntimeError(
                f"Revision 0046 preflight found {violations} row(s) violating {name}; "
                "no schema mutation was attempted."
            )
    invalid_decisions = bind.execute(
        sa.text(
            """
            SELECT COUNT(*)
            FROM draftingeligibilitydisposition
            WHERE decision NOT IN (
                'accepted', 'exception_approved', 'deferred', 'consolidate'
            )
            """
        )
    ).scalar_one()
    if invalid_decisions:
        raise RuntimeError(
            "Revision 0046 cannot replace the disposition vocabulary: "
            f"{invalid_decisions} row(s) use a non-canonical decision. "
            "No value is remapped implicitly."
        )


def _preflight_timestamp_conversions(bind: Any) -> None:
    timezone = str(
        bind.exec_driver_sql("SELECT current_setting('TimeZone')").scalar_one()
    )
    if timezone.casefold() not in {"utc", "etc/utc"}:
        raise RuntimeError(
            "Revision 0046 UTC timestamp preflight requires session TimeZone=UTC; "
            f"observed {timezone!r}. No type mutation was attempted."
        )
    for key in sorted(TIMESTAMPTZ_COLUMNS):
        table, column = _split_key(key)
        violations = bind.exec_driver_sql(
            f'''SELECT COUNT(*) FROM "{table}"
                WHERE "{column}" IS NULL
                   OR NOT isfinite("{column}")
                   OR (("{column}" AT TIME ZONE 'UTC') AT TIME ZONE 'UTC')
                      IS DISTINCT FROM "{column}"'''
        ).scalar_one()
        if violations:
            raise RuntimeError(
                "Revision 0046 UTC timestamp preflight found "
                f"{violations} non-finite, non-round-tripping, or null row(s) in {key}; "
                "no type mutation was attempted."
            )


def _lock_existing_application_tables(bind: Any, tables: frozenset[str]) -> None:
    # A stable global ordering avoids lock-order inversions.  These locks make
    # the data preflight and subsequent sequence synchronization one atomic
    # contract with respect to application writes.
    for table in sorted(tables - {"alembic_version"}):
        bind.exec_driver_sql(f'LOCK TABLE "{table}" IN SHARE ROW EXCLUSIVE MODE')


def _create_runtime_tables() -> None:
    op.create_table(
        "wordpressmetadatastate",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("payload_hash", sa.String(), nullable=True),
        sa.Column("wordpress_revision", sa.String(), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("last_wordpress_metadata_sync_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="wordpressmetadatastate_generated_page_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="wordpressmetadatastate_pkey"),
        sa.UniqueConstraint(
            "generated_page_id",
            name="uq_wordpressmetadatastate_generated_page_id",
        ),
    )
    op.create_table(
        "wordpressmetadatasyncaudit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("wordpress_post_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("wordpress_site_url", sa.String(), nullable=False),
        sa.Column("payload_hash", sa.String(), nullable=False),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.Column("previous_snapshot", sa.JSON(), nullable=True),
        sa.Column("returned_snapshot", sa.JSON(), nullable=True),
        sa.Column("gate_results", sa.JSON(), nullable=False),
        sa.Column("data_backup_file_name", sa.String(), nullable=False),
        sa.Column("wordpress_backup_reference", sa.String(), nullable=False),
        sa.Column("plugin_version", sa.String(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="wordpressmetadatasyncaudit_generated_page_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="wordpressmetadatasyncaudit_pkey"),
        sa.UniqueConstraint(
            "generated_page_id",
            "attempted_at",
            "payload_hash",
            name="uq_wordpressmetadatasyncaudit_page_time_hash",
        ),
    )
    op.create_table(
        "wordpressqualityreview",
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=False),
        sa.Column("review_status", sa.String(), nullable=False),
        sa.Column("reviewer_notes", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="wordpressqualityreview_generated_page_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="wordpressqualityreview_pkey"),
        sa.UniqueConstraint(
            "generated_page_id",
            name="uq_wordpressqualityreview_generated_page_id",
        ),
    )
    for table, indexes in RUNTIME_INDEXES.items():
        for name, columns in indexes.items():
            op.create_index(name, table, list(columns), unique=False)


def _apply_postgres_convergence(source: Literal["clean", "active"]) -> None:
    if source == "clean":
        _create_runtime_tables()

    if source == "active":
        for key in sorted(TIMESTAMPTZ_COLUMNS):
            table, column = _split_key(key)
            op.alter_column(
                table,
                column,
                existing_type=sa.DateTime(timezone=False),
                type_=sa.DateTime(timezone=True),
                existing_nullable=False,
                postgresql_using=f'"{column}" AT TIME ZONE \'UTC\'',
            )
        op.alter_column(
            "draftingeligibilityassessment",
            "status",
            existing_type=sa.String(length=64),
            type_=sa.String(),
            existing_nullable=False,
        )
        op.alter_column(
            "draftingeligibilitydisposition",
            "decision",
            existing_type=sa.String(length=32),
            type_=sa.String(),
            existing_nullable=False,
        )
        for key, contract in SERVER_DEFAULTS.items():
            table, column = _split_key(key)
            op.alter_column(table, column, server_default=sa.text(contract.sql))
        for (table, name), expression in CHECKS_TO_ADD.items():
            op.create_check_constraint(name, table, expression)
        op.drop_constraint(
            DISPOSITION_CHECK[1],
            DISPOSITION_CHECK[0],
            type_="check",
        )
        op.create_check_constraint(
            DISPOSITION_CHECK[1],
            DISPOSITION_CHECK[0],
            CANONICAL_DISPOSITION_EXPRESSION,
        )
        op.drop_index(
            "ix_draftingeligibilitydisposition_accepted_exception",
            table_name="draftingeligibilitydisposition",
        )
    else:
        op.alter_column(
            "wordpressdeploymentaudit",
            "partial_failure_details",
            existing_type=sa.Text(),
            type_=sa.String(),
            existing_nullable=True,
            postgresql_using="partial_failure_details::character varying",
        )
        for name in (
            "ix_wordpressbootstrapcleanupaudit_action_type",
            "ix_wordpresspluginupgradeaudit_action_type",
        ):
            contract = RELEVANT_INDEXES[name]
            op.create_index(name, contract.table, list(contract.key_columns), unique=False)


def _sequence_restart_target(
    *, maximum_id: int | None, last_value: int, is_called: bool, increment: int = 1
) -> int | None:
    required_next = (maximum_id or 0) + increment
    current_next = last_value + increment if is_called else last_value
    return required_next if current_next < required_next else None


def _sync_postgres_sequences(bind: Any) -> None:
    for sequence in sorted(ACTIVE_SEQUENCES):
        table = sequence.removesuffix("_id_seq")
        maximum_id = bind.exec_driver_sql(
            f'SELECT MAX("id") FROM "{table}"'
        ).scalar_one()
        state = bind.exec_driver_sql(
            f'SELECT last_value, is_called FROM "{sequence}"'
        ).one()
        restart = _sequence_restart_target(
            maximum_id=int(maximum_id) if maximum_id is not None else None,
            last_value=int(state[0]),
            is_called=bool(state[1]),
        )
        if restart is not None:
            # ALTER SEQUENCE RESTART participates in the surrounding PostgreSQL
            # transaction; setval() deliberately is not used because it does not.
            bind.exec_driver_sql(
                f'ALTER SEQUENCE "{sequence}" RESTART WITH {restart}'
            )


def _upgrade_postgresql(bind: Any) -> None:
    _require_frozen_catalog_manifest_digests()
    _require_supported_postgresql_major(bind)
    source_surface = _read_postgres_surface(bind)
    source = _classify_postgres_surface(source_surface)
    _lock_existing_application_tables(bind, source_surface.tables)
    locked_surface = _read_postgres_surface(bind)
    if locked_surface != source_surface:
        raise RuntimeError(
            "Revision 0046 PostgreSQL schema changed while locks were acquired; "
            "no schema mutation was attempted."
        )
    if source == "active":
        _preflight_timestamp_conversions(bind)
    _preflight_canonical_data(bind)
    _apply_postgres_convergence(source)
    _sync_postgres_sequences(bind)
    observed = _read_postgres_surface(bind, post_upgrade=True)
    expected = _expected_postgres_surface("canonical")
    if observed != expected:
        differences = ", ".join(_surface_mismatches(observed, expected))
        raise RuntimeError(
            "Revision 0046 canonical PostgreSQL validation failed; the transaction "
            "will roll back. "
            f"Observed manifest {observed.catalog_manifest_sha256}; expected "
            f"{expected.catalog_manifest_sha256}. Differing surfaces: {differences}."
        )


def _classify_sqlite_runtime(bind: Any) -> Literal["clean", "active"]:
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "generatedpage" not in tables:
        raise RuntimeError(
            "Revision 0046 SQLite ownership preflight requires generatedpage; "
            "no schema mutation was attempted."
        )
    present = RUNTIME_TABLES & tables
    if not present:
        return "clean"
    if present != RUNTIME_TABLES:
        raise RuntimeError(
            "Revision 0046 rejected a partial SQLite runtime-table shape before DDL: "
            + ", ".join(sorted(present))
        )
    mismatched = []
    for table in sorted(RUNTIME_TABLES):
        if _runtime_table_signature(bind, table) != _expected_runtime_signature(
            table, postgresql=False
        ):
            mismatched.append(table)
    if mismatched:
        raise RuntimeError(
            "Revision 0046 rejected incompatible SQLite runtime table(s) before DDL: "
            + ", ".join(mismatched)
        )
    return "active"


def _upgrade_sqlite(bind: Any) -> None:
    source = _classify_sqlite_runtime(bind)
    if source == "clean":
        _create_runtime_tables()
    for table in sorted(RUNTIME_TABLES):
        observed = _runtime_table_signature(bind, table)
        expected = _expected_runtime_signature(table, postgresql=False)
        if observed != expected:
            raise RuntimeError(
                f"Revision 0046 SQLite post-create validation failed for {table}."
            )


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        _upgrade_postgresql(bind)
    elif dialect == "sqlite":
        _upgrade_sqlite(bind)
    else:
        raise RuntimeError(
            f"Revision 0046 supports only PostgreSQL and SQLite, not {dialect!r}."
        )


def downgrade() -> None:
    # The two accepted 0045 inputs are intentionally different and cannot be
    # reconstructed from the canonical schema without out-of-band provenance.
    # Fail before inspecting or mutating any database object on every dialect.
    raise RuntimeError(
        "Revision 0046 is intentionally irreversible: canonical head cannot be "
        "downgraded unambiguously to either accepted 0045 schema variant. "
        "Restore an accepted 0045 backup instead; no mutation was attempted."
    )
