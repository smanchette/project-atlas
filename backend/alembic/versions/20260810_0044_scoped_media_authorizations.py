"""Add exact, versioned scoped-media authorization records.

Revision ID: 20260810_0044
Revises: 20260809_0043
"""

import re
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260810_0044"
down_revision = "20260809_0043"
branch_labels = None
depends_on = None


TABLE = "scopedmediaauthorization"
IMAGE_TABLE = "imagemetadata"
IMAGE_MODE_COLUMN = "usage_authorization_mode"
IMAGE_REQUIRED_TERMS_COLUMN = "required_authorization_terms"
IMAGE_MODE_CHECK = "ck_imagemetadata_usage_authorization_mode"
IMAGE_REQUIRED_TERMS_CHECK = "ck_imagemetadata_required_authorization_terms"
IMAGE_MODE_INDEX = "ix_imagemetadata_usage_authorization_mode"
IMAGE_MODE_SQL = (
    "usage_authorization_mode IN ('contract_default','scoped_required')"
)
IMAGE_REQUIRED_TERMS_SQL = (
    "(usage_authorization_mode = 'contract_default' "
    "AND json_array_length(required_authorization_terms) = 0) OR "
    "(usage_authorization_mode = 'scoped_required' "
    "AND json_array_length(required_authorization_terms) >= 1)"
)
CURRENT_INDEX = "uq_scopedmediaauth_current_requirement"
CURRENT_PREDICATE = "lifecycle_status = 'current'"
REQUIREMENT_ONLY_INDEX = "uq_scopedmediaauth_current_requirement_only_asset"
REQUIREMENT_ONLY_PREDICATE = (
    "lifecycle_status = 'current' AND reuse_policy = 'requirement_only'"
)
REUSE_POLICY_CHECK = (
    "reuse_policy IN ('contract_default','requirement_only','page_only',"
    "'website_limited','explicitly_reusable')"
)
LIFECYCLE_CHECK = "lifecycle_status IN ('current','superseded')"
VERSION_CHECK = (
    "requirement_version >= 1 AND placement_contract_version >= 1 "
    "AND media_version >= 1 AND approval_version >= 1 "
    "AND authorization_version >= 1"
)
ASSIGNMENT_PAIR_CHECK = (
    "(page_image_assignment_id IS NULL AND assignment_version IS NULL) "
    "OR (page_image_assignment_id IS NOT NULL "
    "AND assignment_version IS NOT NULL AND assignment_version >= 1)"
)
REQUIRED_TEXT_CHECK = (
    "length(trim(placement_key)) > 0 "
    "AND length(trim(asset_approved_by)) > 0 "
    "AND length(trim(authorized_by)) > 0 "
    "AND length(trim(authorization_rationale)) > 0"
)
FINGERPRINT_CHECK = (
    "length(asset_checksum_sha256) = 64 "
    "AND asset_checksum_sha256 = lower(asset_checksum_sha256) "
    "AND length(approval_fingerprint) = 64 "
    "AND approval_fingerprint = lower(approval_fingerprint) "
    "AND length(authorization_fingerprint) = 64 "
    "AND authorization_fingerprint = lower(authorization_fingerprint)"
)
LINEAGE_CHECK = (
    "(authorization_version = 1 AND supersedes_authorization_id IS NULL) "
    "OR (authorization_version > 1 AND supersedes_authorization_id IS NOT NULL)"
)
NOT_SELF_CHECK = (
    "supersedes_authorization_id IS NULL OR supersedes_authorization_id != id"
)

EXPECTED_COLUMN_SPECS = {
    "created_at": ("datetime", None, False, None),
    "updated_at": ("datetime", None, False, None),
    "id": ("integer", None, False, None),
    "website_id": ("integer", None, False, None),
    "site_plan_id": ("integer", None, False, None),
    "planned_page_id": ("integer", None, False, None),
    "generated_page_id": ("integer", None, True, None),
    "media_requirement_id": ("integer", None, False, None),
    "requirement_version": ("integer", None, False, None),
    "placement_key": ("string", 120, False, None),
    "placement_contract_version": ("integer", None, False, None),
    "image_metadata_id": ("integer", None, False, None),
    "media_version": ("integer", None, False, None),
    "asset_checksum_sha256": ("string", 64, False, None),
    "approval_version": ("integer", None, False, None),
    "asset_approved_by": ("string", 160, False, None),
    "asset_approved_at": ("datetime", None, False, None),
    "approval_fingerprint": ("string", 64, False, None),
    "page_image_assignment_id": ("integer", None, True, None),
    "assignment_version": ("integer", None, True, None),
    "reuse_policy": ("string", 40, False, None),
    "authorization_terms": ("json", None, False, None),
    "authorized_by": ("string", 160, False, None),
    "authorization_rationale": ("string", None, False, None),
    "authorized_at": ("datetime", None, False, None),
    "authorization_version": ("integer", None, False, None),
    "authorization_fingerprint": ("string", 64, False, None),
    "lifecycle_status": ("string", 24, False, None),
    "supersedes_authorization_id": ("integer", None, True, None),
}
EXPECTED_COLUMNS = set(EXPECTED_COLUMN_SPECS)
EXPECTED_FOREIGN_KEYS = {
    ("website_id", "website", "id"),
    ("site_plan_id", "siteplan", "id"),
    ("planned_page_id", "plannedpage", "id"),
    ("generated_page_id", "generatedpage", "id"),
    ("media_requirement_id", "plannedpagemediarequirement", "id"),
    ("image_metadata_id", "imagemetadata", "id"),
    ("page_image_assignment_id", "pageimageassignment", "id"),
    ("supersedes_authorization_id", TABLE, "id"),
}
BASE_TABLE_COLUMNS = {
    "website": {"id"},
    "siteplan": {"id"},
    "plannedpage": {"id"},
    "generatedpage": {"id"},
    "plannedpagemediarequirement": {"id"},
    "imagemetadata": {"id"},
    "pageimageassignment": {"id"},
}
CHECK_CONTRACTS = {
    "ck_scopedmediaauth_reuse_policy": REUSE_POLICY_CHECK,
    "ck_scopedmediaauth_lifecycle": LIFECYCLE_CHECK,
    "ck_scopedmediaauth_versions": VERSION_CHECK,
    "ck_scopedmediaauth_assignment_pair": ASSIGNMENT_PAIR_CHECK,
    "ck_scopedmediaauth_required_text": REQUIRED_TEXT_CHECK,
    "ck_scopedmediaauth_fingerprints": FINGERPRINT_CHECK,
    "ck_scopedmediaauth_lineage": LINEAGE_CHECK,
    "ck_scopedmediaauth_not_self": NOT_SELF_CHECK,
}
UNIQUE_CONTRACTS = {
    "uq_scopedmediaauth_requirement_version": (
        "media_requirement_id",
        "authorization_version",
    ),
    "uq_scopedmediaauth_fingerprint": ("authorization_fingerprint",),
    "uq_scopedmediaauth_successor": ("supersedes_authorization_id",),
}
DESIRED_INDEXES = {
    "ix_scopedmediaauthorization_website_id": (("website_id",), False),
    "ix_scopedmediaauthorization_site_plan_id": (("site_plan_id",), False),
    "ix_scopedmediaauthorization_planned_page_id": (("planned_page_id",), False),
    "ix_scopedmediaauthorization_generated_page_id": (("generated_page_id",), False),
    "ix_scopedmediaauthorization_media_requirement_id": (
        ("media_requirement_id",),
        False,
    ),
    "ix_scopedmediaauthorization_placement_key": (("placement_key",), False),
    "ix_scopedmediaauthorization_image_metadata_id": (
        ("image_metadata_id",),
        False,
    ),
    "ix_scopedmediaauthorization_page_image_assignment_id": (
        ("page_image_assignment_id",),
        False,
    ),
    "ix_scopedmediaauthorization_reuse_policy": (("reuse_policy",), False),
    "ix_scopedmediaauthorization_authorized_at": (("authorized_at",), False),
    "ix_scopedmediaauthorization_lifecycle_status": (
        ("lifecycle_status",),
        False,
    ),
    "ix_scopedmediaauthorization_supersedes_authorization_id": (
        ("supersedes_authorization_id",),
        False,
    ),
    CURRENT_INDEX: (("media_requirement_id",), True),
    REQUIREMENT_ONLY_INDEX: (("image_metadata_id",), True),
}

# A task-local model scaffold briefly existed before this revision was written.
# It was never an approved durable schema and is adopted only when every
# inspected property matches this exact, known contract and the table is empty.
# Keeping the contract explicit prevents a same-named, operator-created, or
# partially populated table from being treated as migration-owned state.
STALE_VERSION_CHECK = (
    "requirement_version >= 1 AND placement_contract_version >= 1 "
    "AND media_version >= 1 AND approval_version >= 1 "
    "AND assignment_version >= 1 AND authorization_version >= 1"
)
STALE_REQUIRED_TEXT_CHECK = (
    "length(trim(placement_key)) > 0 "
    "AND length(trim(authorized_by)) > 0 "
    "AND length(trim(authorization_rationale)) > 0"
)
STALE_FINGERPRINT_CHECK = (
    "length(asset_checksum_sha256) = 64 "
    "AND asset_checksum_sha256 = lower(asset_checksum_sha256) "
    "AND length(authorization_fingerprint) = 64 "
    "AND authorization_fingerprint = lower(authorization_fingerprint)"
)
STALE_EXPECTED_COLUMN_SPECS = {
    name: spec
    for name, spec in EXPECTED_COLUMN_SPECS.items()
    if name
    not in {
        "asset_approved_by",
        "asset_approved_at",
        "approval_fingerprint",
        "authorization_terms",
    }
}
STALE_EXPECTED_COLUMN_SPECS.update(
    {
        "generated_page_id": ("integer", None, False, None),
        "page_image_assignment_id": ("integer", None, False, None),
        "assignment_version": ("integer", None, False, None),
    }
)
STALE_EXPECTED_COLUMNS = set(STALE_EXPECTED_COLUMN_SPECS)
STALE_CHECK_CONTRACTS = {
    "ck_scopedmediaauth_reuse_policy": REUSE_POLICY_CHECK,
    "ck_scopedmediaauth_lifecycle": LIFECYCLE_CHECK,
    "ck_scopedmediaauth_versions": STALE_VERSION_CHECK,
    "ck_scopedmediaauth_required_text": STALE_REQUIRED_TEXT_CHECK,
    "ck_scopedmediaauth_fingerprints": STALE_FINGERPRINT_CHECK,
    "ck_scopedmediaauth_lineage": LINEAGE_CHECK,
    "ck_scopedmediaauth_not_self": NOT_SELF_CHECK,
}
STALE_UNIQUE_CONTRACTS = {
    name: columns
    for name, columns in UNIQUE_CONTRACTS.items()
    if name != "uq_scopedmediaauth_successor"
}
STALE_DESIRED_INDEXES = {
    name: contract
    for name, contract in DESIRED_INDEXES.items()
    if name != REQUIREMENT_ONLY_INDEX
}


def _inspector() -> Any:
    return sa.inspect(op.get_bind())


def _type_contract(column_type: Any) -> tuple[str, int | None]:
    if isinstance(column_type, sa.Integer):
        return "integer", None
    if isinstance(column_type, sa.String):
        return "string", column_type.length
    if isinstance(column_type, sa.DateTime):
        return "datetime", None
    if isinstance(column_type, sa.JSON):
        return "json", None
    return type(column_type).__name__.lower(), getattr(column_type, "length", None)


def _normalized_default(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    return normalized


def _normalized_text_default(value: Any) -> str | None:
    normalized = _normalized_default(value)
    if normalized is None:
        return None
    normalized = re.sub(
        r"::\s*(?:character\s+varying|text)(?:\(\d+\))?",
        "",
        normalized,
    ).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == "'":
        normalized = normalized[1:-1].replace("''", "'")
    return normalized


def _normalized_json_default(value: Any) -> str | None:
    normalized = _normalized_default(value)
    if normalized is None:
        return None
    normalized = re.sub(r"::\s*jsonb?", "", normalized).strip()
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == "'":
        normalized = normalized[1:-1].replace("''", "'")
    return normalized


def _strip_outer_parentheses(value: str) -> str:
    result = value.strip()
    while result.startswith("(") and result.endswith(")"):
        depth = 0
        quoted = False
        closes_at_end = False
        index = 0
        while index < len(result):
            character = result[index]
            if character == "'":
                if quoted and index + 1 < len(result) and result[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            elif not quoted:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0:
                        closes_at_end = index == len(result) - 1
                        break
            index += 1
        if not closes_at_end:
            break
        result = result[1:-1].strip()
    return result


def _normalized_check_sql(value: Any) -> str:
    normalized = str("" if value is None else value).lower().strip()
    if normalized.startswith("check"):
        normalized = normalized[len("check") :].strip()
    normalized = re.sub(
        r"::\s*(?:character\s+varying|text)(?:\s*\[\s*\])?",
        "",
        normalized,
    )
    for pattern in (
        r"trim\s*\(\s*both\s+from\s+\(\s*([a-z_][a-z0-9_]*)\s*\)\s*\)",
        r"trim\s*\(\s*both\s+from\s+([a-z_][a-z0-9_]*)\s*\)",
        r"btrim\s*\(\s*\(\s*([a-z_][a-z0-9_]*)\s*\)\s*\)",
        r"btrim\s*\(\s*([a-z_][a-z0-9_]*)\s*\)",
    ):
        normalized = re.sub(pattern, r"trim(\1)", normalized)
    normalized = re.sub(r"\(\s*([a-z_][a-z0-9_]*)\s*\)", r"\1", normalized)
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*"
        r"\(\s*\(\s*array\s*\[([^\]]*)\]\s*\)\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = re.sub(
        r"([a-z_][a-z0-9_]*)\s*=\s*any\s*"
        r"\(\s*array\s*\[([^\]]*)\]\s*\)",
        r"\1 in (\2)",
        normalized,
    )
    normalized = normalized.replace("<>", "!=")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return _strip_outer_parentheses(normalized)


def _split_top_level_boolean(value: str, operator: str) -> list[str]:
    marker = f" {operator} "
    parts: list[str] = []
    start = 0
    depth = 0
    quoted = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if quoted and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            quoted = not quoted
            index += 1
            continue
        if not quoted:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(marker, index):
                parts.append(value[start:index].strip())
                index += len(marker)
                start = index
                continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:].strip())
    return parts


def _check_contract_ast(value: Any) -> tuple[Any, ...]:
    expression = _strip_outer_parentheses(_normalized_check_sql(value))
    or_parts = _split_top_level_boolean(expression, "or")
    if len(or_parts) > 1:
        return (
            "or",
            *tuple(sorted((_check_contract_ast(part) for part in or_parts), key=repr)),
        )
    and_parts = _split_top_level_boolean(expression, "and")
    if len(and_parts) > 1:
        return (
            "and",
            *tuple(sorted((_check_contract_ast(part) for part in and_parts), key=repr)),
        )
    return "atom", re.sub(r"\s+", "", expression)


def _inspected_check_contracts(inspector: Any) -> dict[str, str]:
    checks = inspector.get_check_constraints(TABLE)
    names = [item.get("name") for item in checks]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise RuntimeError(f"Existing {TABLE} table has an unexpected CHECK contract.")
    return {
        str(item["name"]): str(item.get("sqltext") or "")
        for item in checks
    }


def _validate_check_contracts(
    inspector: Any,
    *,
    contracts: dict[str, str] = CHECK_CONTRACTS,
) -> None:
    observed = _inspected_check_contracts(inspector)
    if set(observed) != set(contracts):
        raise RuntimeError(f"Existing {TABLE} table has an unexpected CHECK contract.")
    for name, expected in contracts.items():
        if _check_contract_ast(observed[name]) != _check_contract_ast(expected):
            raise RuntimeError(f"Existing {TABLE} table has a malformed {name} CHECK.")


def _validate_foreign_key_contracts(inspector: Any) -> None:
    inspected = inspector.get_foreign_keys(TABLE)
    observed = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_schema"),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            tuple(
                sorted(
                    (str(key).lower(), str(value).lower())
                    for key, value in (item.get("options") or {}).items()
                )
            ),
        )
        for item in inspected
    }
    expected = {
        ((column,), None, table, (referred,), ())
        for column, table, referred in EXPECTED_FOREIGN_KEYS
    }
    if len(inspected) != len(EXPECTED_FOREIGN_KEYS) or observed != expected:
        raise RuntimeError(
            f"Existing {TABLE} table has an incompatible foreign key contract."
        )


def _validate_unique_contracts(
    inspector: Any,
    *,
    contracts: dict[str, tuple[str, ...]] = UNIQUE_CONTRACTS,
) -> None:
    constraints = inspector.get_unique_constraints(TABLE)
    observed = {
        str(item.get("name")): tuple(item.get("column_names") or ())
        for item in constraints
    }
    if observed != contracts:
        raise RuntimeError(
            f"Existing {TABLE} table has an incompatible unique contract."
        )


def _index_predicate(index: dict[str, Any]) -> Any:
    options = index.get("dialect_options") or {}
    predicate = options.get("postgresql_where")
    if predicate is None:
        predicate = options.get("sqlite_where")
    return predicate


def _normalized_index_predicate(index: dict[str, Any]) -> str:
    predicate = _index_predicate(index)
    normalized = _strip_outer_parentheses(_normalized_check_sql(predicate))
    return re.sub(r"\s+", "", normalized)


def _validate_index_contracts(
    inspector: Any,
    *,
    require_all: bool,
    contracts: dict[str, tuple[tuple[str, ...], bool]] = DESIRED_INDEXES,
) -> None:
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes(TABLE)
        if item.get("name") and not item.get("duplicates_constraint")
    }
    if not set(indexes).issubset(contracts):
        raise RuntimeError(f"Existing {TABLE} table has unexpected indexes.")
    if require_all and set(indexes) != set(contracts):
        raise RuntimeError(f"Existing {TABLE} table is missing required indexes.")
    for name, item in indexes.items():
        columns, unique = contracts[name]
        malformed = (
            tuple(item.get("column_names") or ()) != columns
            or bool(item.get("unique")) != unique
        )
        predicate = _index_predicate(item)
        if name == CURRENT_INDEX:
            malformed = malformed or _check_contract_ast(
                predicate
            ) != _check_contract_ast(CURRENT_PREDICATE)
        elif name == REQUIREMENT_ONLY_INDEX:
            malformed = malformed or _check_contract_ast(
                predicate
            ) != _check_contract_ast(REQUIREMENT_ONLY_PREDICATE)
        else:
            malformed = malformed or predicate is not None
        if malformed:
            raise RuntimeError(f"Existing {TABLE} table has a malformed {name} index.")


def _validate_image_mode_contract() -> None:
    """Add/backfill the asset gate or adopt only its exact model contract."""

    inspector = _inspector()
    columns = {item["name"]: item for item in inspector.get_columns(IMAGE_TABLE)}
    preexisting = IMAGE_MODE_COLUMN in columns
    if preexisting:
        column = columns[IMAGE_MODE_COLUMN]
        observed = (
            *_type_contract(column["type"]),
            bool(column["nullable"]),
            _normalized_text_default(column.get("default")),
        )
        if observed != ("string", 32, False, "contract_default"):
            raise RuntimeError(
                f"Existing {IMAGE_TABLE}.{IMAGE_MODE_COLUMN} column is incompatible."
            )
        checks = {
            item.get("name"): item.get("sqltext")
            for item in inspector.get_check_constraints(IMAGE_TABLE)
        }
        if (
            IMAGE_MODE_CHECK not in checks
            or _check_contract_ast(checks[IMAGE_MODE_CHECK])
            != _check_contract_ast(IMAGE_MODE_SQL)
        ):
            raise RuntimeError(
                f"Existing {IMAGE_TABLE}.{IMAGE_MODE_COLUMN} CHECK is incompatible."
            )
    else:
        with op.batch_alter_table(IMAGE_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    IMAGE_MODE_COLUMN,
                    sa.String(length=32),
                    nullable=False,
                    server_default=sa.text("'contract_default'"),
                )
            )
            batch_op.create_check_constraint(IMAGE_MODE_CHECK, IMAGE_MODE_SQL)

    inspector = _inspector()
    columns = {item["name"]: item for item in inspector.get_columns(IMAGE_TABLE)}
    terms_preexisting = IMAGE_REQUIRED_TERMS_COLUMN in columns
    if terms_preexisting:
        terms_column = columns[IMAGE_REQUIRED_TERMS_COLUMN]
        observed_terms = (
            *_type_contract(terms_column["type"]),
            bool(terms_column["nullable"]),
            _normalized_json_default(terms_column.get("default")),
        )
        if observed_terms != ("json", None, False, "[]"):
            raise RuntimeError(
                f"Existing {IMAGE_TABLE}.{IMAGE_REQUIRED_TERMS_COLUMN} column "
                "is incompatible."
            )
        checks = {
            item.get("name"): item.get("sqltext")
            for item in inspector.get_check_constraints(IMAGE_TABLE)
        }
        if (
            IMAGE_REQUIRED_TERMS_CHECK not in checks
            or _check_contract_ast(checks[IMAGE_REQUIRED_TERMS_CHECK])
            != _check_contract_ast(IMAGE_REQUIRED_TERMS_SQL)
        ):
            raise RuntimeError(
                f"Existing {IMAGE_TABLE}.{IMAGE_REQUIRED_TERMS_COLUMN} CHECK "
                "is incompatible."
            )
    else:
        with op.batch_alter_table(IMAGE_TABLE) as batch_op:
            batch_op.add_column(
                sa.Column(
                    IMAGE_REQUIRED_TERMS_COLUMN,
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'"),
                )
            )
            batch_op.create_check_constraint(
                IMAGE_REQUIRED_TERMS_CHECK,
                IMAGE_REQUIRED_TERMS_SQL,
            )

    inspector = _inspector()
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes(IMAGE_TABLE)
        if item.get("name") and not item.get("duplicates_constraint")
    }
    mode_index = indexes.get(IMAGE_MODE_INDEX)
    if mode_index is None:
        op.create_index(
            IMAGE_MODE_INDEX,
            IMAGE_TABLE,
            [IMAGE_MODE_COLUMN],
            unique=False,
        )
    elif (
        tuple(mode_index.get("column_names") or ()) != (IMAGE_MODE_COLUMN,)
        or bool(mode_index.get("unique"))
        or _normalized_index_predicate(mode_index)
    ):
        raise RuntimeError(f"Existing {IMAGE_MODE_INDEX} index is incompatible.")

    # Reinspect every semantic property after DDL/backfill and reject unexpected
    # values even if the database reports a CHECK that appears compatible.
    inspector = _inspector()
    column = {
        item["name"]: item for item in inspector.get_columns(IMAGE_TABLE)
    }.get(IMAGE_MODE_COLUMN)
    if column is None or (
        *_type_contract(column["type"]),
        bool(column["nullable"]),
        _normalized_text_default(column.get("default")),
    ) != ("string", 32, False, "contract_default"):
        raise RuntimeError(
            f"{IMAGE_TABLE}.{IMAGE_MODE_COLUMN} was not normalized exactly."
        )
    terms_column = {
        item["name"]: item for item in inspector.get_columns(IMAGE_TABLE)
    }.get(IMAGE_REQUIRED_TERMS_COLUMN)
    if terms_column is None or (
        *_type_contract(terms_column["type"]),
        bool(terms_column["nullable"]),
        _normalized_json_default(terms_column.get("default")),
    ) != ("json", None, False, "[]"):
        raise RuntimeError(
            f"{IMAGE_TABLE}.{IMAGE_REQUIRED_TERMS_COLUMN} was not normalized exactly."
        )
    checks = {
        item.get("name"): item.get("sqltext")
        for item in inspector.get_check_constraints(IMAGE_TABLE)
    }
    if (
        IMAGE_MODE_CHECK not in checks
        or _check_contract_ast(checks[IMAGE_MODE_CHECK])
        != _check_contract_ast(IMAGE_MODE_SQL)
    ):
        raise RuntimeError(f"{IMAGE_TABLE}.{IMAGE_MODE_COLUMN} CHECK is malformed.")
    if (
        IMAGE_REQUIRED_TERMS_CHECK not in checks
        or _check_contract_ast(checks[IMAGE_REQUIRED_TERMS_CHECK])
        != _check_contract_ast(IMAGE_REQUIRED_TERMS_SQL)
    ):
        raise RuntimeError(
            f"{IMAGE_TABLE}.{IMAGE_REQUIRED_TERMS_COLUMN} CHECK is malformed."
        )
    indexes = {
        item["name"]: item
        for item in inspector.get_indexes(IMAGE_TABLE)
        if item.get("name") and not item.get("duplicates_constraint")
    }
    mode_index = indexes.get(IMAGE_MODE_INDEX)
    if (
        mode_index is None
        or tuple(mode_index.get("column_names") or ()) != (IMAGE_MODE_COLUMN,)
        or bool(mode_index.get("unique"))
        or _normalized_index_predicate(mode_index)
    ):
        raise RuntimeError(f"{IMAGE_MODE_INDEX} index was not created exactly.")
    invalid = op.get_bind().execute(
        sa.text(
            f"SELECT COUNT(*) FROM {IMAGE_TABLE} "
            f"WHERE {IMAGE_MODE_COLUMN} NOT IN "
            "('contract_default','scoped_required') "
            f"OR {IMAGE_MODE_COLUMN} IS NULL"
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(
            f"Existing {IMAGE_TABLE}.{IMAGE_MODE_COLUMN} values are incompatible."
        )
    invalid_terms = op.get_bind().execute(
        sa.text(
            f"SELECT COUNT(*) FROM {IMAGE_TABLE} WHERE "
            f"({IMAGE_MODE_COLUMN} = 'contract_default' AND "
            f"json_array_length({IMAGE_REQUIRED_TERMS_COLUMN}) != 0) OR "
            f"({IMAGE_MODE_COLUMN} = 'scoped_required' AND "
            f"json_array_length({IMAGE_REQUIRED_TERMS_COLUMN}) < 1) OR "
            f"{IMAGE_REQUIRED_TERMS_COLUMN} IS NULL"
        )
    ).scalar_one()
    if invalid_terms:
        raise RuntimeError(
            f"Existing {IMAGE_TABLE}.{IMAGE_REQUIRED_TERMS_COLUMN} values are "
            "incompatible."
        )


def _create_table() -> None:
    op.create_table(
        TABLE,
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("website_id", sa.Integer(), nullable=False),
        sa.Column("site_plan_id", sa.Integer(), nullable=False),
        sa.Column("planned_page_id", sa.Integer(), nullable=False),
        sa.Column("generated_page_id", sa.Integer(), nullable=True),
        sa.Column("media_requirement_id", sa.Integer(), nullable=False),
        sa.Column("requirement_version", sa.Integer(), nullable=False),
        sa.Column("placement_key", sa.String(length=120), nullable=False),
        sa.Column("placement_contract_version", sa.Integer(), nullable=False),
        sa.Column("image_metadata_id", sa.Integer(), nullable=False),
        sa.Column("media_version", sa.Integer(), nullable=False),
        sa.Column("asset_checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("approval_version", sa.Integer(), nullable=False),
        sa.Column("asset_approved_by", sa.String(length=160), nullable=False),
        sa.Column("asset_approved_at", sa.DateTime(), nullable=False),
        sa.Column("approval_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("page_image_assignment_id", sa.Integer(), nullable=True),
        sa.Column("assignment_version", sa.Integer(), nullable=True),
        sa.Column("reuse_policy", sa.String(length=40), nullable=False),
        sa.Column("authorization_terms", sa.JSON(), nullable=False),
        sa.Column("authorized_by", sa.String(length=160), nullable=False),
        sa.Column("authorization_rationale", sa.String(), nullable=False),
        sa.Column("authorized_at", sa.DateTime(), nullable=False),
        sa.Column("authorization_version", sa.Integer(), nullable=False),
        sa.Column("authorization_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=24), nullable=False),
        sa.Column("supersedes_authorization_id", sa.Integer(), nullable=True),
        sa.CheckConstraint(REUSE_POLICY_CHECK, name="ck_scopedmediaauth_reuse_policy"),
        sa.CheckConstraint(LIFECYCLE_CHECK, name="ck_scopedmediaauth_lifecycle"),
        sa.CheckConstraint(VERSION_CHECK, name="ck_scopedmediaauth_versions"),
        sa.CheckConstraint(
            ASSIGNMENT_PAIR_CHECK,
            name="ck_scopedmediaauth_assignment_pair",
        ),
        sa.CheckConstraint(
            REQUIRED_TEXT_CHECK,
            name="ck_scopedmediaauth_required_text",
        ),
        sa.CheckConstraint(
            FINGERPRINT_CHECK,
            name="ck_scopedmediaauth_fingerprints",
        ),
        sa.CheckConstraint(LINEAGE_CHECK, name="ck_scopedmediaauth_lineage"),
        sa.CheckConstraint(NOT_SELF_CHECK, name="ck_scopedmediaauth_not_self"),
        sa.ForeignKeyConstraint(
            ["website_id"],
            ["website.id"],
            name="fk_scopedmediaauth_website_id",
        ),
        sa.ForeignKeyConstraint(
            ["site_plan_id"],
            ["siteplan.id"],
            name="fk_scopedmediaauth_site_plan_id",
        ),
        sa.ForeignKeyConstraint(
            ["planned_page_id"],
            ["plannedpage.id"],
            name="fk_scopedmediaauth_planned_page_id",
        ),
        sa.ForeignKeyConstraint(
            ["generated_page_id"],
            ["generatedpage.id"],
            name="fk_scopedmediaauth_generated_page_id",
        ),
        sa.ForeignKeyConstraint(
            ["media_requirement_id"],
            ["plannedpagemediarequirement.id"],
            name="fk_scopedmediaauth_media_requirement_id",
        ),
        sa.ForeignKeyConstraint(
            ["image_metadata_id"],
            ["imagemetadata.id"],
            name="fk_scopedmediaauth_image_metadata_id",
        ),
        sa.ForeignKeyConstraint(
            ["page_image_assignment_id"],
            ["pageimageassignment.id"],
            name="fk_scopedmediaauth_assignment_id",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_authorization_id"],
            [f"{TABLE}.id"],
            name="fk_scopedmediaauth_supersedes_id",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_requirement_id",
            "authorization_version",
            name="uq_scopedmediaauth_requirement_version",
        ),
        sa.UniqueConstraint(
            "authorization_fingerprint",
            name="uq_scopedmediaauth_fingerprint",
        ),
        sa.UniqueConstraint(
            "supersedes_authorization_id",
            name="uq_scopedmediaauth_successor",
        ),
    )


def _create_missing_indexes() -> None:
    existing = {item["name"] for item in _inspector().get_indexes(TABLE)}
    for name, (columns, unique) in DESIRED_INDEXES.items():
        if name in existing:
            continue
        options: dict[str, Any] = {}
        if name == CURRENT_INDEX:
            options = {
                "postgresql_where": sa.text(CURRENT_PREDICATE),
                "sqlite_where": sa.text(CURRENT_PREDICATE),
            }
        elif name == REQUIREMENT_ONLY_INDEX:
            options = {
                "postgresql_where": sa.text(REQUIREMENT_ONLY_PREDICATE),
                "sqlite_where": sa.text(REQUIREMENT_ONLY_PREDICATE),
            }
        op.create_index(name, TABLE, list(columns), unique=unique, **options)


def _column_matches_contract(
    name: str,
    column: dict[str, Any],
    expected: tuple[str, int | None, bool, str | None],
) -> bool:
    observed = (
        *_type_contract(column["type"]),
        bool(column["nullable"]),
        _normalized_default(column.get("default")),
    )
    if observed == expected:
        return True
    # PostgreSQL represents an integer autoincrement primary key as this exact
    # sequence default. SQLite reports no default for the same model contract.
    return bool(
        name == "id"
        and op.get_bind().dialect.name == "postgresql"
        and expected == ("integer", None, False, None)
        and observed
        == (
            "integer",
            None,
            False,
            "nextval('scopedmediaauthorization_id_seq'::regclass)",
        )
    )


def _validate_table_contract(
    inspector: Any,
    *,
    column_specs: dict[str, tuple[str, int | None, bool, str | None]],
    check_contracts: dict[str, str],
    unique_contracts: dict[str, tuple[str, ...]],
    index_contracts: dict[str, tuple[tuple[str, ...], bool]],
    require_all_indexes: bool,
) -> None:
    columns = {item["name"]: item for item in inspector.get_columns(TABLE)}
    if set(columns) != set(column_specs):
        raise RuntimeError(f"Existing {TABLE} table has incompatible columns.")
    for name, expected in column_specs.items():
        if not _column_matches_contract(name, columns[name], expected):
            raise RuntimeError(f"Existing {TABLE} has an incompatible {name} column.")
    primary_key = inspector.get_pk_constraint(TABLE)
    if tuple(primary_key.get("constrained_columns") or ()) != ("id",):
        raise RuntimeError(f"Existing {TABLE} table has an incompatible primary key.")
    _validate_foreign_key_contracts(inspector)
    _validate_unique_contracts(inspector, contracts=unique_contracts)
    _validate_check_contracts(inspector, contracts=check_contracts)
    _validate_index_contracts(
        inspector,
        require_all=require_all_indexes,
        contracts=index_contracts,
    )


def _classify_existing_empty_table() -> str:
    """Lock and classify only the final table or the known empty scaffold."""

    bind = op.get_bind()
    if TABLE not in set(_inspector().get_table_names()):
        return "missing"
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f'LOCK TABLE "{TABLE}" IN ACCESS EXCLUSIVE MODE'))
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table must be empty for adoption.")
    inspector = _inspector()
    columns = {item["name"] for item in inspector.get_columns(TABLE)}
    if columns == EXPECTED_COLUMNS:
        _validate_table_contract(
            inspector,
            column_specs=EXPECTED_COLUMN_SPECS,
            check_contracts=CHECK_CONTRACTS,
            unique_contracts=UNIQUE_CONTRACTS,
            index_contracts=DESIRED_INDEXES,
            require_all_indexes=False,
        )
        classification = "final"
    elif columns == STALE_EXPECTED_COLUMNS:
        _validate_table_contract(
            inspector,
            column_specs=STALE_EXPECTED_COLUMN_SPECS,
            check_contracts=STALE_CHECK_CONTRACTS,
            unique_contracts=STALE_UNIQUE_CONTRACTS,
            index_contracts=STALE_DESIRED_INDEXES,
            require_all_indexes=True,
        )
        classification = "stale_scaffold"
    else:
        raise RuntimeError(f"Existing {TABLE} table has incompatible columns.")
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table is no longer empty.")
    return classification


def _upgrade_exact_empty_stale_scaffold() -> None:
    """Normalize the exact empty task-local scaffold without replacing it."""

    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table must remain empty for adoption.")
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.add_column(
            sa.Column("asset_approved_by", sa.String(length=160), nullable=False)
        )
        batch_op.add_column(
            sa.Column("asset_approved_at", sa.DateTime(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("approval_fingerprint", sa.String(length=64), nullable=False)
        )
        batch_op.add_column(
            sa.Column("authorization_terms", sa.JSON(), nullable=False)
        )
        batch_op.alter_column(
            "generated_page_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.alter_column(
            "page_image_assignment_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.alter_column(
            "assignment_version",
            existing_type=sa.Integer(),
            nullable=True,
        )
        for name in (
            "ck_scopedmediaauth_versions",
            "ck_scopedmediaauth_required_text",
            "ck_scopedmediaauth_fingerprints",
        ):
            batch_op.drop_constraint(name, type_="check")
        batch_op.create_check_constraint(
            "ck_scopedmediaauth_versions",
            VERSION_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_scopedmediaauth_assignment_pair",
            ASSIGNMENT_PAIR_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_scopedmediaauth_required_text",
            REQUIRED_TEXT_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_scopedmediaauth_fingerprints",
            FINGERPRINT_CHECK,
        )
        batch_op.create_unique_constraint(
            "uq_scopedmediaauth_successor",
            ["supersedes_authorization_id"],
        )
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table changed during empty adoption.")


def _finalize_exact_empty_model_table() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table must be empty for adoption.")
    _create_missing_indexes()
    _validate_table_contract(
        _inspector(),
        column_specs=EXPECTED_COLUMN_SPECS,
        check_contracts=CHECK_CONTRACTS,
        unique_contracts=UNIQUE_CONTRACTS,
        index_contracts=DESIRED_INDEXES,
        require_all_indexes=True,
    )
    if bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one() != 0:
        raise RuntimeError(f"Existing {TABLE} table is no longer empty.")


def upgrade() -> None:
    inspector = _inspector()
    existing = set(inspector.get_table_names())
    missing_tables = sorted(set(BASE_TABLE_COLUMNS) - existing)
    if missing_tables:
        raise RuntimeError(
            "Required scoped-media authorization tables are missing: "
            + ", ".join(missing_tables)
        )
    for table, required_columns in BASE_TABLE_COLUMNS.items():
        observed = {item["name"] for item in inspector.get_columns(table)}
        if not required_columns.issubset(observed):
            raise RuntimeError(
                f"Required scoped-media authorization columns are missing from {table}."
            )
    table_contract = _classify_existing_empty_table()
    _validate_image_mode_contract()
    if table_contract == "missing":
        _create_table()
        _create_missing_indexes()
        _finalize_exact_empty_model_table()
    else:
        if table_contract == "stale_scaffold":
            _upgrade_exact_empty_stale_scaffold()
        _finalize_exact_empty_model_table()


def downgrade() -> None:
    tables = set(_inspector().get_table_names())
    if TABLE in tables and op.get_bind().execute(
        sa.text(f"SELECT COUNT(*) FROM {TABLE}")
    ).scalar_one():
        raise RuntimeError(
            "Downgrade blocked: durable scoped-media authorizations exist."
        )
    image_columns = (
        {item["name"] for item in _inspector().get_columns(IMAGE_TABLE)}
        if IMAGE_TABLE in tables
        else set()
    )
    if IMAGE_MODE_COLUMN in image_columns:
        scoped_required = op.get_bind().execute(
            sa.text(
                f"SELECT COUNT(*) FROM {IMAGE_TABLE} "
                f"WHERE {IMAGE_MODE_COLUMN} != 'contract_default'"
            )
        ).scalar_one()
        if scoped_required:
            raise RuntimeError(
                "Downgrade blocked: scoped-required Image Metadata exists."
            )
    if TABLE in tables:
        op.drop_table(TABLE)
    if (
        IMAGE_MODE_COLUMN in image_columns
        or IMAGE_REQUIRED_TERMS_COLUMN in image_columns
    ):
        image_indexes = {
            item.get("name") for item in _inspector().get_indexes(IMAGE_TABLE)
        }
        if IMAGE_MODE_INDEX in image_indexes:
            op.drop_index(IMAGE_MODE_INDEX, table_name=IMAGE_TABLE)
        image_checks = {
            item.get("name")
            for item in _inspector().get_check_constraints(IMAGE_TABLE)
        }
        with op.batch_alter_table(IMAGE_TABLE) as batch_op:
            if IMAGE_REQUIRED_TERMS_CHECK in image_checks:
                batch_op.drop_constraint(
                    IMAGE_REQUIRED_TERMS_CHECK,
                    type_="check",
                )
            if IMAGE_MODE_CHECK in image_checks:
                batch_op.drop_constraint(IMAGE_MODE_CHECK, type_="check")
            if IMAGE_REQUIRED_TERMS_COLUMN in image_columns:
                batch_op.drop_column(IMAGE_REQUIRED_TERMS_COLUMN)
            if IMAGE_MODE_COLUMN in image_columns:
                batch_op.drop_column(IMAGE_MODE_COLUMN)
