"""Add Website-scoped page-media planning and governed media provenance.

Revision ID: 20260807_0041
Revises: 20260805_0040
"""

from alembic import op
import re
import sqlalchemy as sa


revision = "20260807_0041"
down_revision = "20260805_0040"
branch_labels = None
depends_on = None


IMAGE_COLUMNS: dict[str, sa.Column] = {
    "website_id": sa.Column("website_id", sa.Integer(), nullable=True),
    "media_key": sa.Column("media_key", sa.String(length=120), nullable=True),
    "media_version": sa.Column("media_version", sa.Integer(), nullable=True),
    "mime_type": sa.Column("mime_type", sa.String(), nullable=True),
    "file_size": sa.Column("file_size", sa.Integer(), nullable=True),
    "width": sa.Column("width", sa.Integer(), nullable=True),
    "height": sa.Column("height", sa.Integer(), nullable=True),
    "checksum_sha256": sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
    "managed_storage_path": sa.Column("managed_storage_path", sa.String(), nullable=True),
    "acquisition_source": sa.Column("acquisition_source", sa.String(), nullable=True),
    "creator_source_identity": sa.Column("creator_source_identity", sa.String(), nullable=True),
    "created_by": sa.Column("created_by", sa.String(), nullable=True),
    "provenance_type": sa.Column("provenance_type", sa.String(), nullable=True),
    "provenance_notes": sa.Column("provenance_notes", sa.String(), nullable=True),
    "rights_status": sa.Column("rights_status", sa.String(), nullable=True),
    "rights_holder": sa.Column("rights_holder", sa.String(), nullable=True),
    "rights_notes": sa.Column("rights_notes", sa.String(), nullable=True),
    "approved_usage": sa.Column("approved_usage", sa.JSON(), nullable=True),
    "prohibited_usage": sa.Column("prohibited_usage", sa.JSON(), nullable=True),
    "permitted_placement_keys": sa.Column("permitted_placement_keys", sa.JSON(), nullable=True),
    "accessibility_intent": sa.Column("accessibility_intent", sa.String(), nullable=True),
    "governance_status": sa.Column(
        "governance_status",
        sa.String(length=32),
        nullable=False,
        server_default="legacy_unverified",
    ),
    "approval_version": sa.Column("approval_version", sa.Integer(), nullable=True),
    "approved_by": sa.Column("approved_by", sa.String(), nullable=True),
    "approved_at": sa.Column("approved_at", sa.DateTime(), nullable=True),
    "retired_by": sa.Column("retired_by", sa.String(), nullable=True),
    "retirement_rationale": sa.Column("retirement_rationale", sa.String(), nullable=True),
    "retired_at": sa.Column("retired_at", sa.DateTime(), nullable=True),
    "replaces_image_metadata_id": sa.Column(
        "replaces_image_metadata_id", sa.Integer(), nullable=True
    ),
    "gps_metadata_status": sa.Column(
        "gps_metadata_status", sa.String(length=32), nullable=True
    ),
    "gps_metadata": sa.Column("gps_metadata", sa.JSON(), nullable=True),
    "gps_authorized_by": sa.Column("gps_authorized_by", sa.String(), nullable=True),
    "gps_authorized_at": sa.Column("gps_authorized_at", sa.DateTime(), nullable=True),
    "gps_authorization_notes": sa.Column(
        "gps_authorization_notes", sa.String(), nullable=True
    ),
}

ASSIGNMENT_COLUMNS: dict[str, sa.Column] = {
    "website_id": sa.Column("website_id", sa.Integer(), nullable=True),
    "site_plan_id": sa.Column("site_plan_id", sa.Integer(), nullable=True),
    "planned_page_id": sa.Column("planned_page_id", sa.Integer(), nullable=True),
    "media_requirement_id": sa.Column("media_requirement_id", sa.Integer(), nullable=True),
    "assignment_version": sa.Column("assignment_version", sa.Integer(), nullable=True),
    "media_version": sa.Column("media_version", sa.Integer(), nullable=True),
    "placement_contract_version": sa.Column(
        "placement_contract_version", sa.Integer(), nullable=True
    ),
    "assigned_by": sa.Column("assigned_by", sa.String(), nullable=True),
    "assignment_rationale": sa.Column("assignment_rationale", sa.String(), nullable=True),
    "assigned_at": sa.Column("assigned_at", sa.DateTime(), nullable=True),
    "replaced_by": sa.Column("replaced_by", sa.String(), nullable=True),
    "replacement_rationale": sa.Column("replacement_rationale", sa.String(), nullable=True),
    "replaced_at": sa.Column("replaced_at", sa.DateTime(), nullable=True),
    "retired_by": sa.Column("retired_by", sa.String(), nullable=True),
    "retirement_rationale": sa.Column("retirement_rationale", sa.String(), nullable=True),
    "retired_at": sa.Column("retired_at", sa.DateTime(), nullable=True),
    "replaces_page_image_assignment_id": sa.Column(
        "replaces_page_image_assignment_id", sa.Integer(), nullable=True
    ),
}

IMAGE_CHECKS = {
    "ck_imagemetadata_governance_status": (
        "governance_status IN "
        "('legacy_unverified','pending_review','approved','rejected','retired')"
    ),
    "ck_imagemetadata_gps_status": (
        "gps_metadata_status IS NULL OR gps_metadata_status IN "
        "('absent','stripped','present_unverified','verified_authorized')"
    ),
    "ck_imagemetadata_media_version": "media_version IS NULL OR media_version >= 1",
    "ck_imagemetadata_approval_version": (
        "approval_version IS NULL OR approval_version >= 1"
    ),
    "ck_imagemetadata_replacement": (
        "(media_version IS NULL AND replaces_image_metadata_id IS NULL) OR "
        "(media_version = 1 AND replaces_image_metadata_id IS NULL) OR "
        "(media_version > 1 AND replaces_image_metadata_id IS NOT NULL)"
    ),
    "ck_imagemetadata_binary_identity": (
        "(file_size IS NULL AND width IS NULL AND height IS NULL "
        "AND mime_type IS NULL AND checksum_sha256 IS NULL) OR "
        "(file_size >= 1 AND width >= 1 AND height >= 1 "
        "AND mime_type IS NOT NULL AND checksum_sha256 IS NOT NULL "
        "AND length(checksum_sha256) = 64)"
    ),
    "ck_imagemetadata_governed_completeness": (
        "governance_status = 'legacy_unverified' OR "
        "(website_id IS NOT NULL AND media_key IS NOT NULL "
        "AND media_version IS NOT NULL AND managed_storage_path IS NOT NULL "
        "AND acquisition_source IS NOT NULL AND creator_source_identity IS NOT NULL "
        "AND provenance_type IS NOT NULL AND provenance_notes IS NOT NULL "
        "AND rights_status IS NOT NULL AND rights_holder IS NOT NULL "
        "AND rights_notes IS NOT NULL AND approved_usage IS NOT NULL "
        "AND prohibited_usage IS NOT NULL AND permitted_placement_keys IS NOT NULL "
        "AND accessibility_intent IS NOT NULL AND created_by IS NOT NULL "
        "AND file_size IS NOT NULL)"
    ),
    "ck_imagemetadata_approval_provenance": (
        "governance_status NOT IN ('approved','retired') OR "
        "(approval_version IS NOT NULL AND approved_by IS NOT NULL "
        "AND approved_at IS NOT NULL)"
    ),
    "ck_imagemetadata_retirement_provenance": (
        "governance_status != 'retired' OR "
        "(retired_by IS NOT NULL AND retirement_rationale IS NOT NULL "
        "AND retired_at IS NOT NULL)"
    ),
    "ck_imagemetadata_gps_authorization": (
        "gps_metadata_status != 'verified_authorized' OR "
        "(gps_metadata IS NOT NULL AND gps_authorized_by IS NOT NULL "
        "AND gps_authorized_at IS NOT NULL AND gps_authorization_notes IS NOT NULL)"
    ),
}

ASSIGNMENT_CHECKS = {
    "ck_pageimageassignment_assignment_version": (
        "assignment_version IS NULL OR assignment_version >= 1"
    ),
    "ck_pageimageassignment_media_version": (
        "media_version IS NULL OR media_version >= 1"
    ),
    "ck_pageimageassignment_contract_version": (
        "placement_contract_version IS NULL OR placement_contract_version >= 1"
    ),
    "ck_pageimageassignment_status": "status IN ('active','replaced','retired')",
    "ck_pageimageassignment_replacement": (
        "(assignment_version IS NULL AND replaces_page_image_assignment_id IS NULL) OR "
        "(assignment_version = 1 AND replaces_page_image_assignment_id IS NULL) OR "
        "(assignment_version > 1 AND replaces_page_image_assignment_id IS NOT NULL)"
    ),
    "ck_pageimageassignment_governed_binding": (
        "(website_id IS NULL AND site_plan_id IS NULL AND planned_page_id IS NULL "
        "AND media_requirement_id IS NULL AND assignment_version IS NULL "
        "AND media_version IS NULL AND placement_contract_version IS NULL "
        "AND assigned_by IS NULL AND assignment_rationale IS NULL "
        "AND assigned_at IS NULL) OR "
        "(website_id IS NOT NULL AND site_plan_id IS NOT NULL "
        "AND planned_page_id IS NOT NULL AND media_requirement_id IS NOT NULL "
        "AND assignment_version IS NOT NULL AND media_version IS NOT NULL "
        "AND placement_contract_version IS NOT NULL AND assigned_by IS NOT NULL "
        "AND assignment_rationale IS NOT NULL AND assigned_at IS NOT NULL)"
    ),
    "ck_pageimageassignment_replacement_provenance": (
        "status != 'replaced' OR "
        "(replaced_by IS NOT NULL AND replacement_rationale IS NOT NULL "
        "AND replaced_at IS NOT NULL)"
    ),
    "ck_pageimageassignment_retirement_provenance": (
        "status != 'retired' OR "
        "(retired_by IS NOT NULL AND retirement_rationale IS NOT NULL "
        "AND retired_at IS NOT NULL)"
    ),
}


def _inspector():
    return sa.inspect(op.get_bind())


def _tables() -> set[str]:
    return set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {
        item["name"]
        for item in _inspector().get_indexes(table)
        if item.get("name")
    }


def _checks(table: str) -> dict[str, str]:
    return {
        item["name"]: item.get("sqltext") or ""
        for item in _inspector().get_check_constraints(table)
        if item.get("name")
    }


def _uniques(table: str) -> dict[str, tuple[str, ...]]:
    return {
        item["name"]: tuple(item.get("column_names") or ())
        for item in _inspector().get_unique_constraints(table)
        if item.get("name")
    }


def _foreign_keys(table: str) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            tuple(item.get("constrained_columns") or ()),
            str(item.get("referred_table") or ""),
            tuple(item.get("referred_columns") or ()),
        )
        for item in _inspector().get_foreign_keys(table)
    }


def _canonical(expression: str) -> str:
    normalized = " ".join(
        expression.lower().replace('"', "").replace("`", "").split()
    )
    if normalized.startswith("check "):
        normalized = normalized[6:].strip()
    # PostgreSQL rewrites text membership checks to = ANY / <> ALL array
    # expressions and adds dialect casts. Normalize that representation back to
    # the migration-authored IN / NOT IN form without weakening value checks.
    normalized = re.sub(
        r"::(?:character\s+varying|varchar|text|integer|bigint)(?:\[\])?",
        "",
        normalized,
    )
    normalized = re.sub(
        r"\(([a-z_][a-z0-9_]*)\)\s*=\s*any\s*"
        r"\(\s*\(\s*array\[([^\]]*)\]\s*\)\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = re.sub(
        r"\(([a-z_][a-z0-9_]*)\)\s*(?:<>|!=)\s*all\s*"
        r"\(\s*\(\s*array\[([^\]]*)\]\s*\)\s*\)",
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
                return (
                    f"{operator}("
                    + ",".join(canonical_boolean(part) for part in parts)
                    + ")"
                )
        return "".join(strip_outer(value).split())

    return canonical_boolean(normalized)


def _ensure_indexes(table: str, columns: tuple[str, ...]) -> None:
    existing = _indexes(table)
    for column in columns:
        name = f"ix_{table}_{column}"
        if name not in existing:
            op.create_index(name, table, [column])


def _add_missing_columns(table: str, definitions: dict[str, sa.Column]) -> None:
    missing = [name for name in definitions if name not in _columns(table)]
    if missing:
        with op.batch_alter_table(table) as batch_op:
            for name in missing:
                batch_op.add_column(definitions[name])
    required = set(definitions)
    if not required.issubset(_columns(table)):
        raise RuntimeError(f"Existing {table} table is incompatible.")


def _ensure_checks(table: str, required: dict[str, str]) -> None:
    existing = _checks(table)
    missing = [name for name in required if name not in existing]
    if missing:
        with op.batch_alter_table(table) as batch_op:
            for name in missing:
                batch_op.create_check_constraint(name, required[name])
        existing = _checks(table)
    for name, expression in required.items():
        observed = existing.get(name)
        if observed is None or _canonical(observed) != _canonical(expression):
            raise RuntimeError(
                f"Existing {table} table is incompatible: {name} differs."
            )


def _require_checks(table: str, required: dict[str, str]) -> None:
    existing = _checks(table)
    for name, expression in required.items():
        observed = existing.get(name)
        if observed is None or _canonical(observed) != _canonical(expression):
            raise RuntimeError(
                f"Existing {table} table is incompatible: {name} differs."
            )


def _ensure_unique(table: str, name: str, columns: tuple[str, ...]) -> None:
    existing = _uniques(table)
    if name not in existing:
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_unique_constraint(name, list(columns))
        existing = _uniques(table)
    if existing.get(name) != columns:
        raise RuntimeError(
            f"Existing {table} table is incompatible: {name} differs."
        )


def _require_unique(table: str, name: str, columns: tuple[str, ...]) -> None:
    if _uniques(table).get(name) != columns:
        raise RuntimeError(
            f"Existing {table} table is incompatible: {name} differs."
        )


def _ensure_foreign_key(
    table: str,
    *,
    name: str,
    local_column: str,
    referred_table: str,
    referred_column: str = "id",
) -> None:
    signature = ((local_column,), referred_table, (referred_column,))
    if signature not in _foreign_keys(table):
        with op.batch_alter_table(table) as batch_op:
            batch_op.create_foreign_key(
                name,
                referred_table,
                [local_column],
                [referred_column],
            )
    if signature not in _foreign_keys(table):
        raise RuntimeError(
            f"Existing {table} table is incompatible: {local_column} foreign key differs."
        )


def _require_foreign_key(
    table: str,
    *,
    local_column: str,
    referred_table: str,
    referred_column: str = "id",
) -> None:
    signature = ((local_column,), referred_table, (referred_column,))
    if signature not in _foreign_keys(table):
        raise RuntimeError(
            f"Existing {table} table is incompatible: {local_column} foreign key differs."
        )


def _create_or_validate_media_planning_record() -> None:
    table = "websitemediaplanningrecord"
    required_columns = {
        "created_at", "updated_at", "id", "website_id", "business_id",
        "site_plan_id", "version", "algorithm_version",
        "generated_media_suggestions", "source_snapshot", "source_hash",
        "generated_at", "replaces_record_id",
    }
    checks = {"ck_websitemediaplanningrecord_version": "version >= 1"}
    if table not in _tables():
        op.create_table(
            table,
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("algorithm_version", sa.String(length=80), nullable=False),
            sa.Column("generated_media_suggestions", sa.JSON(), nullable=False),
            sa.Column("source_snapshot", sa.JSON(), nullable=False),
            sa.Column("source_hash", sa.String(length=64), nullable=False),
            sa.Column("generated_at", sa.DateTime(), nullable=False),
            sa.Column("replaces_record_id", sa.Integer(), nullable=True),
            sa.CheckConstraint(
                checks["ck_websitemediaplanningrecord_version"],
                name="ck_websitemediaplanningrecord_version",
            ),
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(
                ["replaces_record_id"], ["websitemediaplanningrecord.id"]
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "site_plan_id",
                "version",
                name="uq_websitemediaplanningrecord_plan_version",
            ),
        )
    elif not required_columns.issubset(_columns(table)):
        raise RuntimeError("Existing websitemediaplanningrecord table is incompatible.")
    _require_checks(table, checks)
    _require_unique(
        table,
        "uq_websitemediaplanningrecord_plan_version",
        ("site_plan_id", "version"),
    )
    for column, referred in (
        ("website_id", "website"),
        ("business_id", "business"),
        ("site_plan_id", "siteplan"),
        ("replaces_record_id", table),
    ):
        _require_foreign_key(table, local_column=column, referred_table=referred)
    _ensure_indexes(
        table,
        (
            "website_id", "business_id", "site_plan_id", "algorithm_version",
            "source_hash", "generated_at", "replaces_record_id",
        ),
    )


def _create_or_validate_media_requirement() -> None:
    table = "plannedpagemediarequirement"
    required_columns = {
        "created_at", "updated_at", "id", "website_id", "business_id",
        "site_plan_id", "planned_page_id", "planning_record_id",
        "component_or_section", "placement_key", "contract_version", "version",
        "requirement_state", "purpose", "customer_outcome", "intended_subject",
        "orientation", "aspect_ratio", "minimum_width", "minimum_height",
        "crop_intent", "focal_point_intent", "responsive_behavior",
        "accessibility_intent", "caption_intent", "approved_source_constraints",
        "permitted_reuse_policy", "replacement_policy", "compatible_page_types",
        "source_suggestion_key", "decided_by", "rationale", "decided_at",
        "lifecycle_status", "replaces_requirement_id",
    }
    checks = {
        "ck_plannedpagemediarequirement_contract_version": "contract_version >= 1",
        "ck_plannedpagemediarequirement_version": "version >= 1",
        "ck_plannedpagemediarequirement_minimum_width": "minimum_width >= 1",
        "ck_plannedpagemediarequirement_minimum_height": "minimum_height >= 1",
        "ck_plannedpagemediarequirement_state": (
            "requirement_state IN ('required','advisory','excluded','deferred')"
        ),
        "ck_plannedpagemediarequirement_lifecycle": (
            "lifecycle_status IN ('active','superseded','retired')"
        ),
        "ck_plannedpagemediarequirement_replacement": (
            "(version = 1 AND replaces_requirement_id IS NULL) OR "
            "(version > 1 AND replaces_requirement_id IS NOT NULL)"
        ),
    }
    if table not in _tables():
        op.create_table(
            table,
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("website_id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("site_plan_id", sa.Integer(), nullable=False),
            sa.Column("planned_page_id", sa.Integer(), nullable=False),
            sa.Column("planning_record_id", sa.Integer(), nullable=False),
            sa.Column("component_or_section", sa.String(length=120), nullable=False),
            sa.Column("placement_key", sa.String(length=120), nullable=False),
            sa.Column("contract_version", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("requirement_state", sa.String(), nullable=False),
            sa.Column("purpose", sa.String(), nullable=False),
            sa.Column("customer_outcome", sa.String(), nullable=False),
            sa.Column("intended_subject", sa.String(), nullable=False),
            sa.Column("orientation", sa.String(length=40), nullable=False),
            sa.Column("aspect_ratio", sa.String(length=40), nullable=False),
            sa.Column("minimum_width", sa.Integer(), nullable=False),
            sa.Column("minimum_height", sa.Integer(), nullable=False),
            sa.Column("crop_intent", sa.String(), nullable=False),
            sa.Column("focal_point_intent", sa.String(), nullable=False),
            sa.Column("responsive_behavior", sa.String(), nullable=False),
            sa.Column("accessibility_intent", sa.String(), nullable=False),
            sa.Column("caption_intent", sa.String(), nullable=True),
            sa.Column("approved_source_constraints", sa.JSON(), nullable=False),
            sa.Column("permitted_reuse_policy", sa.String(), nullable=False),
            sa.Column("replacement_policy", sa.String(), nullable=False),
            sa.Column("compatible_page_types", sa.JSON(), nullable=False),
            sa.Column("source_suggestion_key", sa.String(length=200), nullable=True),
            sa.Column("decided_by", sa.String(length=160), nullable=False),
            sa.Column("rationale", sa.String(), nullable=False),
            sa.Column("decided_at", sa.DateTime(), nullable=False),
            sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
            sa.Column("replaces_requirement_id", sa.Integer(), nullable=True),
            *[
                sa.CheckConstraint(expression, name=name)
                for name, expression in checks.items()
            ],
            sa.ForeignKeyConstraint(["website_id"], ["website.id"]),
            sa.ForeignKeyConstraint(["business_id"], ["business.id"]),
            sa.ForeignKeyConstraint(["site_plan_id"], ["siteplan.id"]),
            sa.ForeignKeyConstraint(["planned_page_id"], ["plannedpage.id"]),
            sa.ForeignKeyConstraint(
                ["planning_record_id"], ["websitemediaplanningrecord.id"]
            ),
            sa.ForeignKeyConstraint(
                ["replaces_requirement_id"], ["plannedpagemediarequirement.id"]
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "planned_page_id",
                "placement_key",
                "version",
                name="uq_plannedpagemediarequirement_page_key_version",
            ),
        )
    elif not required_columns.issubset(_columns(table)):
        raise RuntimeError("Existing plannedpagemediarequirement table is incompatible.")
    _require_checks(table, checks)
    _require_unique(
        table,
        "uq_plannedpagemediarequirement_page_key_version",
        ("planned_page_id", "placement_key", "version"),
    )
    for column, referred in (
        ("website_id", "website"),
        ("business_id", "business"),
        ("site_plan_id", "siteplan"),
        ("planned_page_id", "plannedpage"),
        ("planning_record_id", "websitemediaplanningrecord"),
        ("replaces_requirement_id", table),
    ):
        _require_foreign_key(table, local_column=column, referred_table=referred)
    _ensure_indexes(
        table,
        (
            "website_id", "business_id", "site_plan_id", "planned_page_id",
            "planning_record_id", "component_or_section", "placement_key",
            "requirement_state", "decided_at", "lifecycle_status",
            "replaces_requirement_id",
        ),
    )
    if "uq_plannedpagemediarequirement_active_placement" not in _indexes(table):
        op.create_index(
            "uq_plannedpagemediarequirement_active_placement",
            table,
            ["planned_page_id", "placement_key"],
            unique=True,
            postgresql_where=sa.text("lifecycle_status = 'active'"),
            sqlite_where=sa.text("lifecycle_status = 'active'"),
        )


def _extend_image_metadata() -> None:
    table = "imagemetadata"
    if table not in _tables():
        raise RuntimeError("Required imagemetadata table is missing; apply migration 0005 first.")
    _add_missing_columns(table, IMAGE_COLUMNS)
    _ensure_foreign_key(
        table,
        name="fk_imagemetadata_website_id_website",
        local_column="website_id",
        referred_table="website",
    )
    _ensure_foreign_key(
        table,
        name="fk_imagemetadata_replaces_image_metadata_id",
        local_column="replaces_image_metadata_id",
        referred_table=table,
    )
    _ensure_checks(table, IMAGE_CHECKS)
    _ensure_unique(
        table,
        "uq_imagemetadata_website_key_version",
        ("website_id", "media_key", "media_version"),
    )
    _ensure_indexes(
        table,
        (
            "website_id", "media_key", "checksum_sha256", "provenance_type",
            "rights_status", "governance_status", "approved_at", "retired_at",
            "replaces_image_metadata_id", "gps_metadata_status", "gps_authorized_at",
        ),
    )


def _extend_page_image_assignment() -> None:
    table = "pageimageassignment"
    if table not in _tables():
        raise RuntimeError(
            "Required pageimageassignment table is missing; apply migration 0005 first."
        )
    _add_missing_columns(table, ASSIGNMENT_COLUMNS)
    for name, column, referred in (
        ("fk_pageimageassignment_website_id_website", "website_id", "website"),
        ("fk_pageimageassignment_site_plan_id_siteplan", "site_plan_id", "siteplan"),
        ("fk_pageimageassignment_planned_page_id_plannedpage", "planned_page_id", "plannedpage"),
        (
            "fk_pageimageassignment_media_requirement_id",
            "media_requirement_id",
            "plannedpagemediarequirement",
        ),
        (
            "fk_pageimageassignment_replaces_assignment_id",
            "replaces_page_image_assignment_id",
            table,
        ),
    ):
        _ensure_foreign_key(
            table,
            name=name,
            local_column=column,
            referred_table=referred,
        )
    _ensure_checks(table, ASSIGNMENT_CHECKS)
    _ensure_unique(
        table,
        "uq_pageimageassignment_requirement_version",
        ("media_requirement_id", "assignment_version"),
    )
    _ensure_indexes(
        table,
        (
            "website_id", "site_plan_id", "planned_page_id", "media_requirement_id",
            "assigned_at", "replaced_at", "retired_at",
            "replaces_page_image_assignment_id",
        ),
    )
    if "uq_pageimageassignment_active_requirement" not in _indexes(table):
        op.create_index(
            "uq_pageimageassignment_active_requirement",
            table,
            ["media_requirement_id"],
            unique=True,
            postgresql_where=sa.text(
                "status = 'active' AND media_requirement_id IS NOT NULL"
            ),
            sqlite_where=sa.text(
                "status = 'active' AND media_requirement_id IS NOT NULL"
            ),
        )


def upgrade() -> None:
    _create_or_validate_media_planning_record()
    _create_or_validate_media_requirement()
    _extend_image_metadata()
    _extend_page_image_assignment()


def _new_data_count(table: str, columns: tuple[str, ...]) -> int:
    predicates = " OR ".join(f"{column} IS NOT NULL" for column in columns)
    return op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {predicates}")
    ).scalar_one()


def _drop_foreign_key_for_column(table: str, column: str) -> None:
    match = next(
        (
            item
            for item in _inspector().get_foreign_keys(table)
            if tuple(item.get("constrained_columns") or ()) == (column,)
        ),
        None,
    )
    if match and match.get("name"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(match["name"], type_="foreignkey")


def downgrade() -> None:
    connection = op.get_bind()
    for table, label in (
        ("plannedpagemediarequirement", "Planned Page media requirements"),
        ("websitemediaplanningrecord", "Website media planning records"),
    ):
        if table in _tables() and connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table}")
        ).scalar_one():
            raise RuntimeError(f"Downgrade blocked: durable {label} exist.")

    image_durable_columns = tuple(
        name for name in IMAGE_COLUMNS if name != "governance_status"
    )
    if _new_data_count("imagemetadata", image_durable_columns):
        raise RuntimeError("Downgrade blocked: governed Image Metadata exists.")
    if connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM imagemetadata "
            "WHERE governance_status != 'legacy_unverified'"
        )
    ).scalar_one():
        raise RuntimeError("Downgrade blocked: governed Image Metadata exists.")
    if _new_data_count("pageimageassignment", tuple(ASSIGNMENT_COLUMNS)):
        raise RuntimeError("Downgrade blocked: governed Page Image Assignments exist.")

    for table, partial_indexes, unique_names, checks, fk_columns, columns in (
        (
            "pageimageassignment",
            ("uq_pageimageassignment_active_requirement",),
            ("uq_pageimageassignment_requirement_version",),
            ASSIGNMENT_CHECKS,
            (
                "website_id", "site_plan_id", "planned_page_id",
                "media_requirement_id", "replaces_page_image_assignment_id",
            ),
            tuple(ASSIGNMENT_COLUMNS),
        ),
        (
            "imagemetadata",
            (),
            ("uq_imagemetadata_website_key_version",),
            IMAGE_CHECKS,
            ("website_id", "replaces_image_metadata_id"),
            tuple(IMAGE_COLUMNS),
        ),
    ):
        removed_columns = set(columns)
        for index in _inspector().get_indexes(table):
            index_name = index.get("name")
            index_columns = set(index.get("column_names") or ())
            if index_name and (
                index_name in partial_indexes
                or bool(index_columns & removed_columns)
            ):
                op.drop_index(index_name, table_name=table)
        with op.batch_alter_table(table) as batch_op:
            existing_uniques = _uniques(table)
            for name in unique_names:
                if name in existing_uniques:
                    batch_op.drop_constraint(name, type_="unique")
            existing_checks = _checks(table)
            for name in checks:
                if name in existing_checks:
                    batch_op.drop_constraint(name, type_="check")
        for column in fk_columns:
            _drop_foreign_key_for_column(table, column)
        with op.batch_alter_table(table) as batch_op:
            existing_columns = _columns(table)
            for column in reversed(columns):
                if column in existing_columns:
                    batch_op.drop_column(column)

    if "plannedpagemediarequirement" in _tables():
        op.drop_table("plannedpagemediarequirement")
    if "websitemediaplanningrecord" in _tables():
        op.drop_table("websitemediaplanningrecord")
