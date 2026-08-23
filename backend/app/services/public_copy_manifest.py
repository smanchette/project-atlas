from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import stat
from typing import Any
import unicodedata

from sqlalchemy import DateTime


PUBLIC_COPY_MANIFEST_SCHEMA = "project-atlas-public-copy-correction-manifest@2"
PUBLIC_COPY_RULESET_SCHEMA = "project-atlas-public-copy-ruleset@1"
PUBLIC_COPY_GIT_BASELINE_COMMIT = (
    "150e022135e5564319b6b4c3e8ce6362be3f49db"
)
PUBLIC_COPY_EXECUTION_SOURCE_SNAPSHOT_ROLE = (
    "final_execution_source_after_production_freeze"
)
PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT = (
    "schema-datetime-utc-rfc3339-v1"
)
PUBLIC_COPY_AUTHORIZATION_PATH = "/authorization/pasted-text.txt"
PUBLIC_COPY_AUTHORIZATION_SHA256 = (
    "190fd04df004d5979217733026b843a02682f060a2ca26e93b5f4a78153bfb81"
)
PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES = 55755
PUBLIC_COPY_AUTHORIZATION_LINE_COUNT = 2120
PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY = (
    "historical and superseded only by explicit active-0048 resume authorization"
)
PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE = (
    "accepted_resume_preflight_seal.authorization.resume"
)
PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING = (
    "UTF-8 without BOM; text_lines joined with LF; no terminal LF"
)
PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES = 1411
PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT = 34
PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256 = (
    "c15036153a5bbd4231cdd5b1c67d0bd1499731f9344c2ac4d4643509cd20a91b"
)
PUBLIC_COPY_ACTIVE_ATLAS_REVISION = "20260820_0048"
PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT = (
    "Supersedes only the original authorization's obsolete 0046/no-migration "
    "history blocker by accepting active Atlas 0048 and append-only composition "
    "history; all other prohibitions and fail-closed gates remain in force."
)
PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH = (
    ".runtime/public-copy-cleanup-progress/recovery/"
    "resume-preflight-20260820-204254Z/public-copy-resume-preflight-seal.json"
)
PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES = 20950
PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256 = (
    "277e13011054d1a1fd9b591c95149e77b8f9ecd3b9319d349f1e0619c87e96b1"
)
PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA = (
    "project-atlas-public-copy-resume-preflight-seal@1"
)
PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS = "PASS_RESUME_BASELINE_SEALED"
PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES = (
    "brand_assets",
    "brands",
    "businesses",
    "cities",
    "counties",
    "drafting_eligibility_assessments",
    "drafting_eligibility_dispositions",
    "image_metadata",
    "knowledge_blocks",
    "navigation_items",
    "navigation_sets",
    "page_image_assignments",
    "planned_page_media_requirements",
    "planned_pages",
    "planning_records",
    "pre_draft_distinctness_briefs",
    "scoped_media_authorizations",
    "semantic_component_definitions",
    "services",
    "site_plans",
    "supporting_page_authorizations",
    "themes",
    "website_city_coverage_decisions",
    "website_county_coverage_decisions",
    "website_identities",
    "website_identity_asset_assignments",
    "website_media_planning_records",
    "website_service_city_coverage_decisions",
    "website_service_county_coverage_decisions",
    "website_service_coverage_decisions",
    "website_theme_selections",
    "websites",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_DATETIME_TEXT_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?$"
)
_PERFORMANCE_LOCAL_V5_LAYOUT_PATH = (
    "frontend/src/components/performanceLocalV5LayoutContract.ts"
)
_PERFORMANCE_LOCAL_V5_LAYOUT_SIZE_BYTES = 92600
_PERFORMANCE_LOCAL_V5_LAYOUT_SHA256 = (
    "1c969808328e3e711b22f50a0e0b8c3e5fc81d46419174bdb1a5b882b5c2a546"
)

_PAGE_BINDING_KEYS = {
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "page_type",
    "working_name",
    "slug",
    "page_identity",
    "current_revision",
    "current_composition",
    "current_qa",
    "expected_new_content_hash",
    "expected_draft_content",
    "expected_revision_required",
    "correction_entry_ids",
    "expected_changed_top_level_fields",
    "expected_public_block_distinctness",
}
_PAGE_IDENTITY_KEYS = {
    "planned_page_status",
    "planned_page_parent_id",
    "service_id",
    "county_id",
    "city_id",
    "generated_page_type",
    "generated_page_slug",
    "generated_page_title",
    "generated_page_status",
    "generated_page_generation_status",
    "generated_page_qa_status",
    "generated_page_meta_title",
    "generated_page_meta_description",
    "generated_page_h1",
    "generated_page_content_body_sha256",
    "generated_page_preserved_state_sha256",
    "generated_page_updated_at",
}
_CURRENT_REVISION_KEYS = {
    "bound_generated_page_revision_id",
    "latest_page_revision_id",
    "latest_page_revision_hash_after",
    "latest_page_revision_row_sha256",
    "binding_kind",
    "content_hash",
    "generated_page_updated_at",
}
_CURRENT_COMPOSITION_KEYS = {
    "id",
    "version",
    "source_hash",
    "history_revision_id",
    "history_revision_hash",
    "history_revision_row_sha256",
    "content_hash",
}
_CURRENT_QA_KEYS = {
    "id",
    "result_hash",
    "source_hash",
    "ruleset_key",
    "ruleset_version",
    "ruleset_hash",
    "readiness_status",
    "preserved_evidence_sha256",
}
_CORRECTION_KEYS = {
    "entry_id",
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "page_type",
    "current_revision_id",
    "latest_page_revision_id",
    "current_content_hash",
    "current_composition_id",
    "current_composition_version",
    "current_composition_source_hash",
    "current_composition_history_revision_id",
    "current_qa_id",
    "current_qa_result_hash",
    "field_path",
    "mirrored_generated_page_field",
    "operation",
    "original_text",
    "normalized_original_fingerprint",
    "finding_category",
    "finding_severity",
    "replacement_text",
    "omission_decision",
    "normalized_expected_fingerprint",
    "source_owner",
    "source_template_identity",
    "governed_facts_used",
    "provenance",
    "rationale",
    "destination_identity",
    "public_destination_item",
    "expected_page_content_hash",
    "reconciliation_status",
    "customer_data",
}
_DESTINATION_IDENTITY_KEYS = {
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "page_type",
    "working_name",
    "slug",
    "service_id",
    "county_id",
    "city_id",
}
_PUBLIC_DESTINATION_ITEM_KEYS = {
    "source_kind",
    "source_record_id",
    "target_planned_page_id",
    "target_generated_page_id",
    "label",
    "slug",
    "description",
    "ruleset_key",
    "ruleset_version",
    "ruleset_hash",
}
_MANIFEST_SEAL_KEYS = {
    "algorithm",
    "canonicalization",
    "canonical_manifest_payload_sha256",
    "ruleset_canonical_payload_sha256",
    "source_backup_sha256",
    "original_authorization_sha256",
    "resume_authorization_sha256",
    "resume_preflight_seal_sha256",
    "operator_intents_snapshot_sha256",
    "expected_page_hashes_sha256",
    "pre_repair_source_module_snapshot_sha256",
    "execution_source_module_list_sha256",
    "locked_source_table_sha256_package_sha256",
    "immutable_history_snapshot_sha256",
    "customer_data",
}


class PublicCopyManifestError(ValueError):
    pass


@dataclass(frozen=True)
class PublicCopyManifestPackage:
    manifest: dict[str, Any]
    ruleset: dict[str, Any]
    manifest_file_sha256: str
    manifest_payload_sha256: str
    ruleset_file_sha256: str
    ruleset_payload_sha256: str
    execution_source_root: str


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def model_datetime_field_contract(model: type[Any]) -> dict[str, bool]:
    """Return the model's exact top-level SQLAlchemy DateTime field contract.

    The mapping is sorted by model field name and records the schema timezone
    flag for audit evidence.  Both timezone-aware and timezone-naive Atlas
    columns use the same canonical UTC representation at Backup/ORM row
    identity boundaries; the flag remains evidence about the declared schema.
    """

    table = getattr(model, "__table__", None)
    columns = getattr(table, "columns", None)
    if table is None or columns is None:
        raise PublicCopyManifestError(
            "Database-row timestamp canonicalization requires one table model."
        )
    contract: dict[str, bool] = {}
    for column in columns:
        key = getattr(column, "key", None)
        name = getattr(column, "name", None)
        if not isinstance(key, str) or not key or not isinstance(name, str) or not name:
            raise PublicCopyManifestError(
                "Table model has an invalid SQLAlchemy column identity."
            )
        if key != name:
            raise PublicCopyManifestError(
                "Table model has an ambiguous SQLAlchemy column key/name mapping."
            )
        if not isinstance(column.type, DateTime):
            continue
        if key in contract:
            raise PublicCopyManifestError(
                "Table model has a duplicate DateTime field identity."
            )
        contract[key] = bool(getattr(column.type, "timezone", False))
    return {field: contract[field] for field in sorted(contract)}


def canonicalize_model_row_timestamps(
    model: type[Any],
    row: dict[str, Any],
) -> dict[str, Any]:
    """Normalize only declared top-level DateTime fields in one row payload."""

    if not isinstance(row, dict):
        raise PublicCopyManifestError(
            "Database-row timestamp canonicalization requires an object row."
        )
    result = dict(row)
    for field in model_datetime_field_contract(model):
        if field not in result or result[field] is None:
            continue
        result[field] = _canonical_schema_datetime(
            result[field],
            field=f"{model.__name__}.{field}",
        )
    return result


def canonical_model_row_sha256(
    model: type[Any],
    row: dict[str, Any],
) -> str:
    return canonical_json_sha256(canonicalize_model_row_timestamps(model, row))


def canonical_model_rows_sha256(
    model: type[Any],
    rows: list[dict[str, Any]],
) -> str:
    if not isinstance(rows, list):
        raise PublicCopyManifestError(
            "Database-row timestamp canonicalization requires an ordered row list."
        )
    return canonical_json_sha256(
        [canonicalize_model_row_timestamps(model, row) for row in rows]
    )


def _canonical_schema_datetime(value: Any, *, field: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        if (
            value != value.strip()
            or _SCHEMA_DATETIME_TEXT_PATTERN.fullmatch(value) is None
        ):
            raise PublicCopyManifestError(
                f"{field} is not an exact ISO-8601 DateTime value."
            )
        try:
            parsed = datetime.fromisoformat(
                value[:-1] + "+00:00" if value.endswith("Z") else value
            )
        except ValueError as exc:
            raise PublicCopyManifestError(
                f"{field} is not a valid ISO-8601 DateTime value."
            ) from exc
    else:
        raise PublicCopyManifestError(
            f"{field} is not a DateTime or ISO-8601 DateTime string."
        )
    if parsed.tzinfo is None:
        normalized = parsed.replace(tzinfo=UTC)
    else:
        try:
            if parsed.utcoffset() is None:
                raise ValueError("timezone has no UTC offset")
            normalized = parsed.astimezone(UTC)
        except (OverflowError, ValueError) as exc:
            raise PublicCopyManifestError(
                f"{field} has an invalid timezone offset."
            ) from exc
    return normalized.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def load_public_copy_manifest_package(
    manifest_path: str | Path,
    *,
    manifest_sha256: str,
    ruleset_path: str | Path,
    ruleset_sha256: str,
    source_root: str | Path | None = None,
) -> PublicCopyManifestPackage:
    expected_manifest_sha = _required_sha256(
        manifest_sha256,
        field="manifest_sha256",
    )
    expected_ruleset_sha = _required_sha256(
        ruleset_sha256,
        field="ruleset_sha256",
    )
    manifest_bytes = _read_regular_file(Path(manifest_path), label="Correction manifest")
    ruleset_bytes = _read_regular_file(Path(ruleset_path), label="Public-copy ruleset")
    observed_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    observed_ruleset_sha = hashlib.sha256(ruleset_bytes).hexdigest()
    if observed_manifest_sha != expected_manifest_sha:
        raise PublicCopyManifestError(
            "Correction-manifest SHA-256 does not match the explicit caller seal."
        )
    if observed_ruleset_sha != expected_ruleset_sha:
        raise PublicCopyManifestError(
            "Public-copy ruleset SHA-256 does not match the explicit caller seal."
        )
    manifest = _strict_json(manifest_bytes, label="Correction manifest")
    ruleset = _strict_json(ruleset_bytes, label="Public-copy ruleset")
    _validate_ruleset(ruleset, file_sha256=observed_ruleset_sha)
    _validate_manifest(
        manifest,
        file_sha256=observed_manifest_sha,
        ruleset=ruleset,
        ruleset_file_sha256=observed_ruleset_sha,
    )
    execution_source_root = _validate_execution_source_snapshot(
        manifest,
        source_root=source_root,
    )
    return PublicCopyManifestPackage(
        manifest=deepcopy(manifest),
        ruleset=deepcopy(ruleset),
        manifest_file_sha256=observed_manifest_sha,
        manifest_payload_sha256=manifest["seal"][
            "canonical_manifest_payload_sha256"
        ],
        ruleset_file_sha256=observed_ruleset_sha,
        ruleset_payload_sha256=ruleset["seal"]["canonical_payload_sha256"],
        execution_source_root=str(execution_source_root),
    )


def revalidate_public_copy_manifest_package(
    package: PublicCopyManifestPackage,
) -> None:
    """Reject any in-memory drift after a SHA-pinned package was loaded."""

    if canonical_json_sha256(
        {key: value for key, value in package.ruleset.items() if key != "seal"}
    ) != package.ruleset_payload_sha256:
        raise PublicCopyManifestError(
            "Public-copy ruleset changed after its caller-sealed load."
        )
    if canonical_json_sha256(
        {key: value for key, value in package.manifest.items() if key != "seal"}
    ) != package.manifest_payload_sha256:
        raise PublicCopyManifestError(
            "Correction manifest changed after its caller-sealed load."
        )
    _validate_ruleset(package.ruleset, file_sha256=package.ruleset_file_sha256)
    _validate_manifest(
        package.manifest,
        file_sha256=package.manifest_file_sha256,
        ruleset=package.ruleset,
        ruleset_file_sha256=package.ruleset_file_sha256,
    )
    _validate_execution_source_snapshot(
        package.manifest,
        source_root=package.execution_source_root,
    )


def _read_regular_file(path: Path, *, label: str) -> bytes:
    if _is_link_or_reparse(path.absolute()):
        raise PublicCopyManifestError(
            f"{label} must be a regular non-symlink file."
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PublicCopyManifestError(f"{label} does not exist: {path}.") from exc
    if not resolved.is_file() or _is_link_or_reparse(resolved):
        raise PublicCopyManifestError(f"{label} must be a regular non-symlink file.")
    return resolved.read_bytes()


def _strict_json(payload: bytes, *, label: str) -> dict[str, Any]:
    if payload.startswith(b"\xef\xbb\xbf"):
        raise PublicCopyManifestError(f"{label} must not contain a UTF-8 BOM.")
    if b"\x00" in payload:
        raise PublicCopyManifestError(f"{label} must not contain NUL bytes.")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PublicCopyManifestError(
                    f"{label} contains a duplicate JSON key: {key}."
                )
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise PublicCopyManifestError(
            f"{label} contains a non-finite JSON number: {value}."
        )

    try:
        decoded = payload.decode("utf-8", errors="strict")
        value = json.loads(
            decoded,
            object_pairs_hook=object_pairs,
            parse_constant=invalid_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicCopyManifestError(f"{label} is not strict UTF-8 JSON.") from exc
    if not isinstance(value, dict):
        raise PublicCopyManifestError(f"{label} must be a JSON object.")
    return value


def _validate_ruleset(ruleset: dict[str, Any], *, file_sha256: str) -> None:
    if ruleset.get("schema") != PUBLIC_COPY_RULESET_SCHEMA:
        raise PublicCopyManifestError("Unsupported public-copy ruleset schema.")
    identity = ruleset.get("identity")
    if not isinstance(identity, str) or not identity.strip() or identity != identity.strip():
        raise PublicCopyManifestError("Public-copy ruleset identity is invalid.")
    for field in ("key", "version"):
        value = ruleset.get(field)
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise PublicCopyManifestError(
                f"Public-copy ruleset {field} is invalid."
            )
    seal = ruleset.get("seal")
    if not isinstance(seal, dict):
        raise PublicCopyManifestError("Public-copy ruleset seal is missing.")
    payload_sha = _required_sha256(
        seal.get("canonical_payload_sha256"),
        field="ruleset.seal.canonical_payload_sha256",
    )
    observed_payload_sha = canonical_json_sha256(
        {key: value for key, value in ruleset.items() if key != "seal"}
    )
    if observed_payload_sha != payload_sha:
        raise PublicCopyManifestError("Public-copy ruleset canonical seal is invalid.")
    if seal.get("customer_data") is not False:
        raise PublicCopyManifestError("Public-copy ruleset must declare customer_data=false.")
    if not _SHA256_PATTERN.fullmatch(file_sha256):
        raise PublicCopyManifestError("Public-copy ruleset file SHA-256 is invalid.")


def _validate_manifest(
    manifest: dict[str, Any],
    *,
    file_sha256: str,
    ruleset: dict[str, Any],
    ruleset_file_sha256: str,
) -> None:
    if manifest.get("schema") != PUBLIC_COPY_MANIFEST_SCHEMA:
        raise PublicCopyManifestError("Unsupported correction-manifest schema.")
    if (
        manifest.get("database_row_timestamp_contract")
        != PUBLIC_COPY_DATABASE_ROW_TIMESTAMP_CONTRACT
    ):
        raise PublicCopyManifestError(
            "Correction manifest has an unsupported database-row timestamp contract."
        )
    if manifest.get("status") != "sealed_pending_disposable_clone_rehearsal":
        raise PublicCopyManifestError("Correction manifest is not in the sealed pre-rehearsal state.")
    if manifest.get("customer_data") is not False:
        raise PublicCopyManifestError("Correction manifest must declare customer_data=false.")
    for counter in (
        "external_request_count",
        "database_read_count",
        "database_write_count",
    ):
        if manifest.get(counter) != 0:
            raise PublicCopyManifestError(
                f"Correction manifest has a nonzero forbidden counter: {counter}."
            )

    seal = manifest.get("seal")
    if not isinstance(seal, dict):
        raise PublicCopyManifestError("Correction-manifest seal is missing.")
    _exact_keys(seal, _MANIFEST_SEAL_KEYS, field="manifest.seal")
    _validate_authorization_binding(manifest, seal=seal)
    payload_sha = _required_sha256(
        seal.get("canonical_manifest_payload_sha256"),
        field="manifest.seal.canonical_manifest_payload_sha256",
    )
    observed_payload_sha = canonical_json_sha256(
        {key: value for key, value in manifest.items() if key != "seal"}
    )
    if observed_payload_sha != payload_sha:
        raise PublicCopyManifestError("Correction-manifest canonical seal is invalid.")
    if seal.get("customer_data") is not False:
        raise PublicCopyManifestError("Correction-manifest seal must declare customer_data=false.")
    if seal.get("ruleset_canonical_payload_sha256") != ruleset["seal"].get(
        "canonical_payload_sha256"
    ):
        raise PublicCopyManifestError("Correction manifest is bound to a different ruleset payload.")
    ruleset_binding = manifest.get("ruleset")
    if not isinstance(ruleset_binding, dict):
        raise PublicCopyManifestError("Correction-manifest ruleset binding is missing.")
    if (
        ruleset_binding.get("schema") != ruleset.get("schema")
        or ruleset_binding.get("identity") != ruleset.get("identity")
        or ruleset_binding.get("canonical_payload_sha256")
        != ruleset["seal"].get("canonical_payload_sha256")
    ):
        raise PublicCopyManifestError("Correction-manifest ruleset identity is inconsistent.")
    if not _SHA256_PATTERN.fullmatch(file_sha256) or not _SHA256_PATTERN.fullmatch(
        ruleset_file_sha256
    ):
        raise PublicCopyManifestError("Caller file seals are invalid.")

    scope = _object(manifest.get("scope"), field="scope")
    if scope.get("customer_data") is not False:
        raise PublicCopyManifestError("Correction-manifest scope must declare customer_data=false.")
    page_count = _positive_int(scope.get("planned_page_count"), field="scope.planned_page_count")
    if _positive_int(scope.get("generated_page_count"), field="scope.generated_page_count") != page_count:
        raise PublicCopyManifestError("Planned/Generated scope counts differ.")
    if _positive_int(scope.get("affected_page_count"), field="scope.affected_page_count") != page_count:
        raise PublicCopyManifestError(
            "This manifest version requires one substantive correction binding for every scoped page."
        )
    _positive_int(scope.get("website_id"), field="scope.website_id")
    _positive_int(scope.get("site_plan_id"), field="scope.site_plan_id")
    _validate_governed_fact_snapshot(manifest)

    page_bindings = manifest.get("page_bindings")
    corrections = manifest.get("corrections")
    if not isinstance(page_bindings, list) or len(page_bindings) != page_count:
        raise PublicCopyManifestError("Correction manifest does not bind the complete page scope.")
    if not isinstance(corrections, list) or not corrections:
        raise PublicCopyManifestError("Correction manifest has no correction entries.")
    binding_by_planned_page = _validate_page_bindings(
        page_bindings,
        scope=scope,
    )
    _validate_immutable_history_snapshot(
        manifest,
        binding_by_planned_page=binding_by_planned_page,
    )
    corrections_by_page, changed_fields_by_page = _validate_correction_ledger(
        corrections,
        scope=scope,
        binding_by_planned_page=binding_by_planned_page,
        ruleset=ruleset,
    )
    if set(binding_by_planned_page) != set(corrections_by_page):
        raise PublicCopyManifestError(
            "Every bound page must own at least one correction."
        )
    for planned_id, binding in binding_by_planned_page.items():
        if binding["correction_entry_ids"] != corrections_by_page[planned_id]:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} correction identities are inconsistent."
            )
        if binding["expected_changed_top_level_fields"] != sorted(
            changed_fields_by_page[planned_id]
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} changed-field ledger is inconsistent."
            )
    _validate_operator_intent_preservation(
        manifest,
        corrections=corrections,
    )


def _validate_authorization_binding(
    manifest: dict[str, Any],
    *,
    seal: dict[str, Any],
) -> None:
    authorization = _object(
        manifest.get("authorization"),
        field="authorization",
    )
    _exact_keys(
        authorization,
        {
            "original",
            "resume_authorization",
            "accepted_resume_preflight_seal",
        },
        field="authorization",
    )
    original = _object(
        authorization.get("original"),
        field="authorization.original",
    )
    _exact_keys(
        original,
        {
            "path",
            "size_bytes",
            "line_count",
            "sha256",
            "historical_boundary_note",
        },
        field="authorization.original",
    )
    if original.get("path") != PUBLIC_COPY_AUTHORIZATION_PATH:
        raise PublicCopyManifestError(
            "Correction-manifest original authorization path is invalid."
        )
    if original.get("sha256") != PUBLIC_COPY_AUTHORIZATION_SHA256:
        raise PublicCopyManifestError(
            "Correction-manifest original authorization identity is invalid."
        )
    if _positive_int(
        original.get("size_bytes"),
        field="authorization.original.size_bytes",
    ) != PUBLIC_COPY_AUTHORIZATION_SIZE_BYTES:
        raise PublicCopyManifestError(
            "Correction-manifest original authorization size is invalid."
        )
    if _positive_int(
        original.get("line_count"),
        field="authorization.original.line_count",
    ) != PUBLIC_COPY_AUTHORIZATION_LINE_COUNT:
        raise PublicCopyManifestError(
            "Correction-manifest original authorization line count is invalid."
        )
    if (
        original.get("historical_boundary_note")
        != PUBLIC_COPY_AUTHORIZATION_ORIGINAL_0046_BOUNDARY
    ):
        raise PublicCopyManifestError(
            "Correction-manifest original authorization historical note is invalid."
        )

    resume = _object(
        authorization.get("resume_authorization"),
        field="authorization.resume_authorization",
    )
    _exact_keys(
        resume,
        {
            "source",
            "canonical_encoding",
            "size_bytes",
            "line_count",
            "sha256",
            "active_atlas_revision",
            "authority_effect",
        },
        field="authorization.resume_authorization",
    )
    if resume.get("source") != PUBLIC_COPY_RESUME_AUTHORIZATION_SOURCE:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization source is invalid."
        )
    if (
        resume.get("canonical_encoding")
        != PUBLIC_COPY_RESUME_AUTHORIZATION_CANONICAL_ENCODING
    ):
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization encoding is invalid."
        )
    if _positive_int(
        resume.get("size_bytes"),
        field="authorization.resume_authorization.size_bytes",
    ) != PUBLIC_COPY_RESUME_AUTHORIZATION_SIZE_BYTES:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization size is invalid."
        )
    if _positive_int(
        resume.get("line_count"),
        field="authorization.resume_authorization.line_count",
    ) != PUBLIC_COPY_RESUME_AUTHORIZATION_LINE_COUNT:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization line count is invalid."
        )
    if resume.get("sha256") != PUBLIC_COPY_RESUME_AUTHORIZATION_SHA256:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization identity is invalid."
        )
    if resume.get("active_atlas_revision") != PUBLIC_COPY_ACTIVE_ATLAS_REVISION:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization Atlas revision is invalid."
        )
    if resume.get("authority_effect") != PUBLIC_COPY_RESUME_AUTHORIZATION_EFFECT:
        raise PublicCopyManifestError(
            "Correction-manifest resume authorization effect is invalid."
        )

    preflight = _object(
        authorization.get("accepted_resume_preflight_seal"),
        field="authorization.accepted_resume_preflight_seal",
    )
    _exact_keys(
        preflight,
        {
            "path",
            "size_bytes",
            "sha256",
            "schema",
            "status",
            "cross_binding",
        },
        field="authorization.accepted_resume_preflight_seal",
    )
    if preflight.get("path") != PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_PATH:
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight seal path is invalid."
        )
    if _positive_int(
        preflight.get("size_bytes"),
        field="authorization.accepted_resume_preflight_seal.size_bytes",
    ) != PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SIZE_BYTES:
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight seal size is invalid."
        )
    if preflight.get("sha256") != PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SHA256:
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight seal identity is invalid."
        )
    if preflight.get("schema") != PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_SCHEMA:
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight seal schema is invalid."
        )
    if preflight.get("status") != PUBLIC_COPY_RESUME_PREFLIGHT_SEAL_STATUS:
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight seal status is invalid."
        )
    cross_binding = _object(
        preflight.get("cross_binding"),
        field="authorization.accepted_resume_preflight_seal.cross_binding",
    )
    _exact_keys(
        cross_binding,
        {
            "original_authorization_sha256",
            "resume_authorization_sha256",
            "active_atlas_revision",
        },
        field="authorization.accepted_resume_preflight_seal.cross_binding",
    )
    if (
        cross_binding.get("original_authorization_sha256") != original["sha256"]
        or cross_binding.get("resume_authorization_sha256") != resume["sha256"]
        or cross_binding.get("active_atlas_revision")
        != resume["active_atlas_revision"]
    ):
        raise PublicCopyManifestError(
            "Correction-manifest resume-preflight cross-binding is invalid."
        )

    sealed_original_sha = _required_sha256(
        seal.get("original_authorization_sha256"),
        field="manifest.seal.original_authorization_sha256",
    )
    sealed_resume_sha = _required_sha256(
        seal.get("resume_authorization_sha256"),
        field="manifest.seal.resume_authorization_sha256",
    )
    sealed_preflight_sha = _required_sha256(
        seal.get("resume_preflight_seal_sha256"),
        field="manifest.seal.resume_preflight_seal_sha256",
    )
    if (
        sealed_original_sha != original["sha256"]
        or sealed_resume_sha != resume["sha256"]
        or sealed_preflight_sha != preflight["sha256"]
    ):
        raise PublicCopyManifestError(
            "Correction-manifest seal is bound to a different authorization bundle."
        )


def _validate_operator_intent_preservation(
    manifest: dict[str, Any],
    *,
    corrections: list[Any],
) -> None:
    contract = _object(
        manifest.get("operator_intent_preservation"),
        field="operator_intent_preservation",
    )
    _exact_keys(
        contract,
        {
            "row_count",
            "canonical_snapshot_sha256",
            "mutation_allowed",
            "public_projection_field",
            "projection_item_count",
            "projection_sha256",
            "destination_target_type_counts",
            "source_page_type_item_counts",
        },
        field="operator_intent_preservation",
    )
    row_count = _positive_int(
        contract.get("row_count"),
        field="operator_intent_preservation.row_count",
    )
    projection_item_count = _positive_int(
        contract.get("projection_item_count"),
        field="operator_intent_preservation.projection_item_count",
    )
    _required_sha256(
        contract.get("canonical_snapshot_sha256"),
        field="operator_intent_preservation.canonical_snapshot_sha256",
    )
    projection_sha256 = _required_sha256(
        contract.get("projection_sha256"),
        field="operator_intent_preservation.projection_sha256",
    )
    if (
        contract.get("mutation_allowed") is not False
        or contract.get("public_projection_field")
        != "draft_content.public_destination_copy"
    ):
        raise PublicCopyManifestError(
            "Operator-intent preservation authority is invalid."
        )
    projection_corrections = [
        correction
        for correction in corrections
        if correction["operation"]
        == "add_destination_derived_public_projection"
    ]
    if row_count != projection_item_count or row_count != len(
        projection_corrections
    ):
        raise PublicCopyManifestError(
            "Operator-intent and public-projection counts differ."
        )
    projection_payload = [
        {
            "source_planned_page_id": correction["planned_page_id"],
            **correction["public_destination_item"],
        }
        for correction in projection_corrections
    ]
    if canonical_json_sha256(projection_payload) != projection_sha256:
        raise PublicCopyManifestError(
            "Operator-intent public-projection hash is inconsistent."
        )

    def exact_counts(value: Any, *, field: str) -> dict[str, int]:
        mapping = _object(value, field=field)
        if not mapping or any(
            not isinstance(key, str)
            or not key
            or key != key.strip()
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            for key, count in mapping.items()
        ):
            raise PublicCopyManifestError(
                f"{field} must contain exact positive type counts."
            )
        return dict(sorted(mapping.items()))

    expected_target_counts = dict(
        sorted(
            Counter(
                correction["destination_identity"]["page_type"]
                for correction in projection_corrections
            ).items()
        )
    )
    expected_source_counts = dict(
        sorted(
            Counter(
                correction["page_type"]
                for correction in projection_corrections
            ).items()
        )
    )
    if exact_counts(
        contract.get("destination_target_type_counts"),
        field="operator_intent_preservation.destination_target_type_counts",
    ) != expected_target_counts or exact_counts(
        contract.get("source_page_type_item_counts"),
        field="operator_intent_preservation.source_page_type_item_counts",
    ) != expected_source_counts:
        raise PublicCopyManifestError(
            "Operator-intent public-projection type counts are inconsistent."
        )


def _validate_governed_fact_snapshot(manifest: dict[str, Any]) -> None:
    snapshot = _object(
        manifest.get("governed_fact_snapshot"),
        field="governed_fact_snapshot",
    )
    expected_keys = {
        "business",
        "brand",
        "website",
        "services_sha256",
        "counties_sha256",
        "cities_sha256",
        "knowledge_blocks_sha256",
        "locked_source_table_sha256",
    }
    _exact_keys(snapshot, expected_keys, field="governed_fact_snapshot")
    business = _object(snapshot["business"], field="governed_fact_snapshot.business")
    brand = _object(snapshot["brand"], field="governed_fact_snapshot.brand")
    website = _object(snapshot["website"], field="governed_fact_snapshot.website")
    _exact_keys(
        business,
        {
            "id",
            "brand_name",
            "company_name",
            "business_type",
            "phone",
            "email",
            "website",
            "main_city",
            "state",
            "license_number",
            "certified_operator",
            "description",
        },
        field="governed_fact_snapshot.business",
    )
    _exact_keys(
        brand,
        {"id", "business_id", "brand_name", "tagline", "description", "status"},
        field="governed_fact_snapshot.brand",
    )
    _exact_keys(
        website,
        {
            "id",
            "business_id",
            "brand_id",
            "website_name",
            "domain",
            "public_url",
            "locale",
        },
        field="governed_fact_snapshot.website",
    )
    business_id = _positive_int(business.get("id"), field="governed_fact_snapshot.business.id")
    brand_id = _positive_int(brand.get("id"), field="governed_fact_snapshot.brand.id")
    if (
        brand.get("business_id") != business_id
        or website.get("business_id") != business_id
        or website.get("brand_id") != brand_id
    ):
        raise PublicCopyManifestError(
            "Governed fact snapshot Business/Brand/Website ownership is inconsistent."
        )
    website_id = _positive_int(
        website.get("id"), field="governed_fact_snapshot.website.id"
    )
    scope = _object(manifest.get("scope"), field="scope")
    if website_id != scope.get("website_id"):
        raise PublicCopyManifestError(
            "Governed fact snapshot Website identity differs from manifest scope."
        )
    for field in (
        "services_sha256",
        "counties_sha256",
        "cities_sha256",
        "knowledge_blocks_sha256",
    ):
        _required_sha256(snapshot.get(field), field=f"governed_fact_snapshot.{field}")
    locked_hashes = _object(
        snapshot.get("locked_source_table_sha256"),
        field="governed_fact_snapshot.locked_source_table_sha256",
    )
    _exact_keys(
        locked_hashes,
        set(PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES),
        field="governed_fact_snapshot.locked_source_table_sha256",
    )
    for table_name in PUBLIC_COPY_LOCKED_SOURCE_TABLE_NAMES:
        _required_sha256(
            locked_hashes.get(table_name),
            field=(
                "governed_fact_snapshot.locked_source_table_sha256."
                f"{table_name}"
            ),
        )


def _validate_immutable_history_snapshot(
    manifest: dict[str, Any],
    *,
    binding_by_planned_page: dict[int, dict[str, Any]],
) -> None:
    snapshot = _object(
        manifest.get("immutable_history_snapshot"),
        field="immutable_history_snapshot",
    )
    table_names = {
        "generated_page_revisions",
        "page_composition_revisions",
        "generated_page_qa_results",
    }
    _exact_keys(snapshot, table_names, field="immutable_history_snapshot")
    for table_name in ("generated_page_revisions", "page_composition_revisions"):
        table = _object(
            snapshot.get(table_name),
            field=f"immutable_history_snapshot.{table_name}",
        )
        _exact_keys(
            table,
            {"row_count", "maximum_id", "canonical_rows_sha256"},
            field=f"immutable_history_snapshot.{table_name}",
        )
        _positive_int(
            table.get("row_count"),
            field=f"immutable_history_snapshot.{table_name}.row_count",
        )
        _positive_int(
            table.get("maximum_id"),
            field=f"immutable_history_snapshot.{table_name}.maximum_id",
        )
        _required_sha256(
            table.get("canonical_rows_sha256"),
            field=(
                f"immutable_history_snapshot.{table_name}."
                "canonical_rows_sha256"
            ),
        )
    qa = _object(
        snapshot.get("generated_page_qa_results"),
        field="immutable_history_snapshot.generated_page_qa_results",
    )
    _exact_keys(
        qa,
        {
            "row_count",
            "maximum_id",
            "canonical_rows_sha256",
            "current_row_ids",
            "canonical_noncurrent_rows_sha256",
            "canonical_current_preserved_rows_sha256",
        },
        field="immutable_history_snapshot.generated_page_qa_results",
    )
    _positive_int(
        qa.get("row_count"),
        field="immutable_history_snapshot.generated_page_qa_results.row_count",
    )
    qa_maximum_id = _positive_int(
        qa.get("maximum_id"),
        field="immutable_history_snapshot.generated_page_qa_results.maximum_id",
    )
    current_ids = qa.get("current_row_ids")
    expected_current_ids = sorted(
        int(binding["current_qa"]["id"])
        for binding in binding_by_planned_page.values()
    )
    if (
        not isinstance(current_ids, list)
        or current_ids != expected_current_ids
        or any(type(value) is not int or value <= 0 for value in current_ids)
        or any(value > qa_maximum_id for value in current_ids)
    ):
        raise PublicCopyManifestError(
            "Immutable QA snapshot current-row identities differ from page bindings."
        )
    for field in (
        "canonical_rows_sha256",
        "canonical_noncurrent_rows_sha256",
        "canonical_current_preserved_rows_sha256",
    ):
        _required_sha256(
            qa.get(field),
            field=f"immutable_history_snapshot.generated_page_qa_results.{field}",
        )


def _validate_page_bindings(
    page_bindings: list[Any],
    *,
    scope: dict[str, Any],
) -> dict[int, dict[str, Any]]:
    binding_by_planned_page: dict[int, dict[str, Any]] = {}
    generated_ids: set[int] = set()
    ordered_ids: list[int] = []
    for index, value in enumerate(page_bindings):
        item = _object(value, field=f"page_bindings[{index}]")
        _exact_keys(item, _PAGE_BINDING_KEYS, field=f"page_bindings[{index}]")
        planned_id = _positive_int(
            item.get("planned_page_id"),
            field=f"page_bindings[{index}].planned_page_id",
        )
        generated_id = _positive_int(
            item.get("generated_page_id"),
            field=f"page_binding[{planned_id}].generated_page_id",
        )
        if planned_id in binding_by_planned_page or generated_id in generated_ids:
            raise PublicCopyManifestError(
                "Page bindings contain duplicate page identities."
            )
        if (
            item.get("website_id") != scope.get("website_id")
            or item.get("site_plan_id") != scope.get("site_plan_id")
        ):
            raise PublicCopyManifestError(
                "Page binding crosses the sealed Website/SitePlan scope."
            )
        page_type = _required_text(
            item.get("page_type"), field=f"page_binding[{planned_id}].page_type"
        )
        working_name = _required_text(
            item.get("working_name"),
            field=f"page_binding[{planned_id}].working_name",
        )
        slug = _required_text(
            item.get("slug"), field=f"page_binding[{planned_id}].slug"
        )

        identity = _object(
            item.get("page_identity"),
            field=f"page_binding[{planned_id}].page_identity",
        )
        _exact_keys(
            identity,
            _PAGE_IDENTITY_KEYS,
            field=f"page_binding[{planned_id}].page_identity",
        )
        for field in ("planned_page_parent_id", "service_id", "county_id", "city_id"):
            _nullable_positive_int(
                identity.get(field),
                field=f"page_binding[{planned_id}].page_identity.{field}",
            )
        if (
            identity.get("generated_page_type") != page_type
            or identity.get("generated_page_slug") != slug
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} Planned/Generated identity is inconsistent."
            )
        for field in (
            "planned_page_status",
            "generated_page_status",
            "generated_page_generation_status",
            "generated_page_qa_status",
            "generated_page_title",
            "generated_page_updated_at",
        ):
            _required_text(
                identity.get(field),
                field=f"page_binding[{planned_id}].page_identity.{field}",
            )
        _required_sha256(
            identity.get("generated_page_content_body_sha256"),
            field=(
                f"page_binding[{planned_id}].page_identity."
                "generated_page_content_body_sha256"
            ),
        )
        _required_sha256(
            identity.get("generated_page_preserved_state_sha256"),
            field=(
                f"page_binding[{planned_id}].page_identity."
                "generated_page_preserved_state_sha256"
            ),
        )

        current_revision = _object(
            item.get("current_revision"),
            field=f"page_binding[{planned_id}].current_revision",
        )
        _exact_keys(
            current_revision,
            _CURRENT_REVISION_KEYS,
            field=f"page_binding[{planned_id}].current_revision",
        )
        current_hash = _required_sha256(
            current_revision.get("content_hash"),
            field=f"page_binding[{planned_id}].current_revision.content_hash",
        )
        if (
            current_revision.get("generated_page_updated_at")
            != identity.get("generated_page_updated_at")
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} Generated Page timestamps are inconsistent."
            )
        binding_kind = current_revision.get("binding_kind")
        bound_revision_id = current_revision.get("bound_generated_page_revision_id")
        latest_revision_id = current_revision.get("latest_page_revision_id")
        latest_hash = current_revision.get("latest_page_revision_hash_after")
        latest_row_hash = current_revision.get("latest_page_revision_row_sha256")
        if binding_kind == "legacy_unbound_root":
            if any(
                value is not None
                for value in (
                    bound_revision_id,
                    latest_revision_id,
                    latest_hash,
                    latest_row_hash,
                )
            ):
                raise PublicCopyManifestError(
                    f"Page binding {planned_id} legacy revision identity is inconsistent."
                )
        elif binding_kind == "canonical_bound":
            if (
                _positive_int(
                    bound_revision_id,
                    field=f"page_binding[{planned_id}].current_revision.bound_generated_page_revision_id",
                )
                != _positive_int(
                    latest_revision_id,
                    field=f"page_binding[{planned_id}].current_revision.latest_page_revision_id",
                )
                or _required_sha256(
                    latest_hash,
                    field=f"page_binding[{planned_id}].current_revision.latest_page_revision_hash_after",
                )
                != current_hash
            ):
                raise PublicCopyManifestError(
                    f"Page binding {planned_id} canonical revision identity is inconsistent."
                )
            _required_sha256(
                latest_row_hash,
                field=f"page_binding[{planned_id}].current_revision.latest_page_revision_row_sha256",
            )
        else:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} has an invalid revision binding kind."
            )

        current_composition = _object(
            item.get("current_composition"),
            field=f"page_binding[{planned_id}].current_composition",
        )
        _exact_keys(
            current_composition,
            _CURRENT_COMPOSITION_KEYS,
            field=f"page_binding[{planned_id}].current_composition",
        )
        for field in ("id", "version", "history_revision_id"):
            _positive_int(
                current_composition.get(field),
                field=f"page_binding[{planned_id}].current_composition.{field}",
            )
        for field in (
            "source_hash",
            "history_revision_hash",
            "history_revision_row_sha256",
            "content_hash",
        ):
            _required_sha256(
                current_composition.get(field),
                field=f"page_binding[{planned_id}].current_composition.{field}",
            )
        if current_composition.get("content_hash") != current_hash:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} composition/current content hashes differ."
            )

        current_qa = _object(
            item.get("current_qa"),
            field=f"page_binding[{planned_id}].current_qa",
        )
        _exact_keys(
            current_qa,
            _CURRENT_QA_KEYS,
            field=f"page_binding[{planned_id}].current_qa",
        )
        _positive_int(
            current_qa.get("id"), field=f"page_binding[{planned_id}].current_qa.id"
        )
        for field in (
            "result_hash",
            "source_hash",
            "ruleset_hash",
            "preserved_evidence_sha256",
        ):
            _required_sha256(
                current_qa.get(field),
                field=f"page_binding[{planned_id}].current_qa.{field}",
            )
        for field in ("ruleset_key", "ruleset_version", "readiness_status"):
            _required_text(
                current_qa.get(field),
                field=f"page_binding[{planned_id}].current_qa.{field}",
            )

        expected_draft = item.get("expected_draft_content")
        if not isinstance(expected_draft, dict):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} lacks its exact expected draft payload."
            )
        expected_hash = _required_sha256(
            item.get("expected_new_content_hash"),
            field=f"page_binding[{planned_id}].expected_new_content_hash",
        )
        if canonical_json_sha256(expected_draft) != expected_hash:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} expected-draft hash is invalid."
            )
        if current_hash == expected_hash:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} would create an empty revision."
            )
        if item.get("expected_revision_required") is not True:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} must require an append-only revision."
            )
        destination_copy = expected_draft.get("public_destination_copy")
        if not isinstance(destination_copy, list) or not destination_copy:
            raise PublicCopyManifestError(
                f"Page binding {planned_id} lacks substantive public destination copy."
            )
        bound_ids = item.get("correction_entry_ids")
        if (
            not isinstance(bound_ids, list)
            or not bound_ids
            or any(not isinstance(value, str) for value in bound_ids)
            or len(bound_ids) != len(set(bound_ids))
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} has an invalid correction-id list."
            )
        changed_fields = item.get("expected_changed_top_level_fields")
        if (
            not isinstance(changed_fields, list)
            or not changed_fields
            or any(
                not isinstance(value, str) or not value or "." in value
                for value in changed_fields
            )
            or changed_fields != sorted(set(changed_fields))
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} has an invalid changed-field ledger."
            )
        distinctness = _object(
            item.get("expected_public_block_distinctness"),
            field=f"page_binding[{planned_id}].expected_public_block_distinctness",
        )
        _exact_keys(
            distinctness,
            {
                "planned_page_id",
                "public_block_count",
                "inventory_sha256",
                "duplicate_group_count",
            },
            field=f"page_binding[{planned_id}].expected_public_block_distinctness",
        )
        if (
            distinctness.get("planned_page_id") != planned_id
            or _positive_int(
                distinctness.get("public_block_count"),
                field=(
                    f"page_binding[{planned_id}].expected_public_block_distinctness."
                    "public_block_count"
                ),
            )
            < 1
            or distinctness.get("duplicate_group_count") != 0
        ):
            raise PublicCopyManifestError(
                f"Page binding {planned_id} public-block distinctness is invalid."
            )
        _required_sha256(
            distinctness.get("inventory_sha256"),
            field=(
                f"page_binding[{planned_id}].expected_public_block_distinctness."
                "inventory_sha256"
            ),
        )
        binding_by_planned_page[planned_id] = item
        generated_ids.add(generated_id)
        ordered_ids.append(planned_id)
    if ordered_ids != sorted(ordered_ids):
        raise PublicCopyManifestError(
            "Page bindings must be sorted by Planned Page identity."
        )
    return binding_by_planned_page


def _validate_correction_ledger(
    corrections: list[Any],
    *,
    scope: dict[str, Any],
    binding_by_planned_page: dict[int, dict[str, Any]],
    ruleset: dict[str, Any],
) -> tuple[dict[int, list[str]], dict[int, set[str]]]:
    correction_ids: set[str] = set()
    corrections_by_page: dict[int, list[str]] = {}
    changed_fields_by_page: dict[int, set[str]] = {}
    for index, value in enumerate(corrections):
        item = _object(value, field=f"corrections[{index}]")
        _exact_keys(item, _CORRECTION_KEYS, field=f"corrections[{index}]")
        entry_id = item.get("entry_id")
        if (
            not isinstance(entry_id, str)
            or re.fullmatch(r"public-copy-correction-[0-9]{4}", entry_id) is None
            or entry_id in correction_ids
        ):
            raise PublicCopyManifestError(
                "Correction entries have a missing, malformed, or duplicate identity."
            )
        correction_ids.add(entry_id)
        planned_id = _positive_int(
            item.get("planned_page_id"),
            field=f"correction[{entry_id}].planned_page_id",
        )
        binding = binding_by_planned_page.get(planned_id)
        if binding is None:
            raise PublicCopyManifestError(
                f"Correction {entry_id} has no exact Planned Page binding."
            )
        current_revision = binding["current_revision"]
        current_composition = binding["current_composition"]
        current_qa = binding["current_qa"]
        exact_bindings = {
            "website_id": scope["website_id"],
            "site_plan_id": scope["site_plan_id"],
            "generated_page_id": binding["generated_page_id"],
            "page_type": binding["page_type"],
            "current_revision_id": current_revision[
                "bound_generated_page_revision_id"
            ],
            "latest_page_revision_id": current_revision["latest_page_revision_id"],
            "current_content_hash": current_revision["content_hash"],
            "current_composition_id": current_composition["id"],
            "current_composition_version": current_composition["version"],
            "current_composition_source_hash": current_composition["source_hash"],
            "current_composition_history_revision_id": current_composition[
                "history_revision_id"
            ],
            "current_qa_id": current_qa["id"],
            "current_qa_result_hash": current_qa["result_hash"],
            "expected_page_content_hash": binding["expected_new_content_hash"],
        }
        for field, expected in exact_bindings.items():
            if item.get(field) != expected:
                raise PublicCopyManifestError(
                    f"Correction {entry_id} {field} contradicts its Page binding."
                )
        if item.get("customer_data") is not False:
            raise PublicCopyManifestError(
                "Every correction must declare customer_data=false."
            )
        if (
            item.get("reconciliation_status")
            != "sealed_pending_disposable_clone_rehearsal"
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} has an invalid reconciliation status."
            )
        operation = item.get("operation")
        if operation not in {
            "replace_exact_value",
            "remove_exact_sentence",
            "add_destination_derived_public_projection",
        }:
            raise PublicCopyManifestError(
                f"Correction {entry_id} has an unsupported operation."
            )
        _validate_operation_path(
            operation=operation,
            field_path=item.get("field_path"),
            entry_id=entry_id,
        )
        original_text = _required_text(
            item.get("original_text"),
            field=f"correction[{entry_id}].original_text",
        )
        replacement_text = item.get("replacement_text")
        if replacement_text is not None and not isinstance(replacement_text, str):
            raise PublicCopyManifestError(
                f"Correction {entry_id} replacement text is invalid."
            )
        if item.get("normalized_original_fingerprint") != _normalized_fingerprint(
            original_text
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} original fingerprint is inconsistent."
            )
        if item.get("normalized_expected_fingerprint") != _normalized_fingerprint(
            replacement_text
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} expected fingerprint is inconsistent."
            )
        for field in (
            "finding_category",
            "source_owner",
            "source_template_identity",
            "rationale",
        ):
            _required_text(
                item.get(field), field=f"correction[{entry_id}].{field}"
            )
        if item.get("finding_severity") not in {"BLOCKER", "WARNING"}:
            raise PublicCopyManifestError(
                f"Correction {entry_id} finding severity is invalid."
            )
        facts = item.get("governed_facts_used")
        if not isinstance(facts, list) or not facts:
            raise PublicCopyManifestError(
                f"Correction {entry_id} lacks exact governed facts."
            )
        for fact_index, fact_value in enumerate(facts):
            fact = _object(
                fact_value,
                field=f"correction[{entry_id}].governed_facts_used[{fact_index}]",
            )
            _exact_keys(
                fact,
                {"fact", "value"},
                field=f"correction[{entry_id}].governed_facts_used[{fact_index}]",
            )
            _required_text(
                fact.get("fact"),
                field=f"correction[{entry_id}].governed_facts_used[{fact_index}].fact",
            )
        _validate_correction_provenance(
            item,
            operation=operation,
            entry_id=entry_id,
        )
        changed_field = _validate_operation_value_coupling(
            item,
            binding=binding,
            binding_by_planned_page=binding_by_planned_page,
            ruleset=ruleset,
        )
        corrections_by_page.setdefault(planned_id, []).append(entry_id)
        changed_fields_by_page.setdefault(planned_id, set()).add(changed_field)
    return corrections_by_page, changed_fields_by_page


def _validate_correction_provenance(
    item: dict[str, Any],
    *,
    operation: str,
    entry_id: str,
) -> None:
    provenance = _object(
        item.get("provenance"), field=f"correction[{entry_id}].provenance"
    )
    if operation == "add_destination_derived_public_projection":
        expected = {
            "classification": (
                "operator_governed_internal_intent_with_generator_owned_public_projection"
            ),
            "operator_authored_content_changed": False,
            "operator_internal_link_intent_preserved": True,
            "automatic_correction_authorized": True,
        }
    else:
        expected = {
            "classification": "generator_owned_exact_template",
            "operator_authored_content_changed": False,
            "automatic_correction_authorized": True,
        }
    if provenance.get("automatic_correction_authorized") is not True:
        raise PublicCopyManifestError(
            f"Correction {entry_id} lacks exact automatic-correction authority."
        )
    if provenance.get("operator_authored_content_changed") is not False:
        raise PublicCopyManifestError(
            f"Correction {entry_id} would change operator-authored content."
        )
    if provenance != expected:
        raise PublicCopyManifestError(
            f"Correction {entry_id} lacks exact automatic-correction provenance."
        )


def _validate_operation_value_coupling(
    item: dict[str, Any],
    *,
    binding: dict[str, Any],
    binding_by_planned_page: dict[int, dict[str, Any]],
    ruleset: dict[str, Any],
) -> str:
    entry_id = item["entry_id"]
    operation = item["operation"]
    field_path = item["field_path"]
    expected_draft = binding["expected_draft_content"]
    original_text = item["original_text"]
    replacement_text = item["replacement_text"]
    if operation == "replace_exact_value":
        if (
            not isinstance(replacement_text, str)
            or not replacement_text
            or replacement_text == original_text
            or item.get("omission_decision") is not False
            or item.get("destination_identity") is not None
            or item.get("public_destination_item") is not None
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} exact-replacement values are inconsistent."
            )
        expected_value = _expected_scalar_value(
            expected_draft, field_path=field_path, entry_id=entry_id
        )
        if expected_value != replacement_text:
            raise PublicCopyManifestError(
                f"Correction {entry_id} replacement contradicts its expected draft."
            )
        expected_mirror = (
            "meta_description"
            if field_path == "draft_content.meta_description"
            else None
        )
        if item.get("mirrored_generated_page_field") != expected_mirror:
            raise PublicCopyManifestError(
                f"Correction {entry_id} mirror-field coupling is invalid."
            )
        return _top_level_field(field_path)

    if operation == "remove_exact_sentence":
        if (
            replacement_text is not None
            or item.get("omission_decision") is not True
            or item.get("mirrored_generated_page_field") is not None
            or item.get("destination_identity") is not None
            or item.get("public_destination_item") is not None
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} exact-omission values are inconsistent."
            )
        base_path, _, suffix = field_path.partition("::")
        match = re.fullmatch(
            r"exact_sentence\[knowledge_block_id=([1-9][0-9]*)\]",
            suffix,
        )
        expected_value = _expected_scalar_value(
            expected_draft, field_path=base_path, entry_id=entry_id
        )
        if original_text in expected_value:
            raise PublicCopyManifestError(
                f"Correction {entry_id} omitted sentence remains in its expected draft."
            )
        knowledge_id = int(match.group(1)) if match else 0
        if not any(
            fact.get("fact") == "knowledge_block.id"
            and fact.get("value") == knowledge_id
            for fact in item["governed_facts_used"]
        ):
            raise PublicCopyManifestError(
                f"Correction {entry_id} omission lacks its exact KnowledgeBlock binding."
            )
        return "sections"

    if (
        not isinstance(replacement_text, str)
        or not replacement_text
        or replacement_text == original_text
        or item.get("omission_decision") is not False
        or item.get("mirrored_generated_page_field") is not None
    ):
        raise PublicCopyManifestError(
            f"Correction {entry_id} destination-projection values are inconsistent."
        )
    path_match = re.fullmatch(
        r"draft_content\.public_destination_copy"
        r"\[source_kind=internal_link_intent,source_record_id=([1-9][0-9]*)\]"
        r"\.description",
        field_path,
    )
    source_record_id = int(path_match.group(1)) if path_match else 0
    destination = _object(
        item.get("destination_identity"),
        field=f"correction[{entry_id}].destination_identity",
    )
    public_item = _object(
        item.get("public_destination_item"),
        field=f"correction[{entry_id}].public_destination_item",
    )
    _exact_keys(
        destination,
        _DESTINATION_IDENTITY_KEYS,
        field=f"correction[{entry_id}].destination_identity",
    )
    _exact_keys(
        public_item,
        _PUBLIC_DESTINATION_ITEM_KEYS,
        field=f"correction[{entry_id}].public_destination_item",
    )
    for field in ("service_id", "county_id", "city_id"):
        _nullable_positive_int(
            destination.get(field),
            field=f"correction[{entry_id}].destination_identity.{field}",
        )
    target_planned_id = _positive_int(
        destination.get("planned_page_id"),
        field=f"correction[{entry_id}].destination_identity.planned_page_id",
    )
    target_binding = binding_by_planned_page.get(target_planned_id)
    if target_binding is None:
        raise PublicCopyManifestError(
            f"Correction {entry_id} destination has no exact scoped Page binding."
        )
    target_identity = target_binding["page_identity"]
    if destination != {
        "website_id": target_binding["website_id"],
        "site_plan_id": target_binding["site_plan_id"],
        "planned_page_id": target_binding["planned_page_id"],
        "generated_page_id": target_binding["generated_page_id"],
        "page_type": target_binding["page_type"],
        "working_name": target_binding["working_name"],
        "slug": target_binding["slug"],
        "service_id": target_identity["service_id"],
        "county_id": target_identity["county_id"],
        "city_id": target_identity["city_id"],
    }:
        raise PublicCopyManifestError(
            f"Correction {entry_id} destination identity contradicts its target Page binding."
        )
    if public_item != {
        "source_kind": "internal_link_intent",
        "source_record_id": source_record_id,
        "target_planned_page_id": destination["planned_page_id"],
        "target_generated_page_id": destination["generated_page_id"],
        "label": destination["working_name"],
        "slug": destination["slug"],
        "description": replacement_text,
        "ruleset_key": ruleset["key"],
        "ruleset_version": ruleset["version"],
        "ruleset_hash": ruleset["seal"]["canonical_payload_sha256"],
    }:
        raise PublicCopyManifestError(
            f"Correction {entry_id} public destination item is inconsistent."
        )
    projected = expected_draft.get("public_destination_copy")
    if not isinstance(projected, list):
        raise PublicCopyManifestError(
            f"Correction {entry_id} expected draft lacks public destination copy."
        )
    matches = [
        value
        for value in projected
        if isinstance(value, dict)
        and value.get("source_kind") == "internal_link_intent"
        and value.get("source_record_id") == source_record_id
    ]
    if matches != [public_item]:
        raise PublicCopyManifestError(
            f"Correction {entry_id} projection contradicts its expected draft."
        )
    return "public_destination_copy"


def _expected_scalar_value(
    draft: dict[str, Any],
    *,
    field_path: str,
    entry_id: str,
) -> str:
    top_match = re.fullmatch(
        r"draft_content\.(intro|meta_description|call_to_action)", field_path
    )
    if top_match:
        value = draft.get(top_match.group(1))
    else:
        section_match = re.fullmatch(
            r"draft_content\.sections\[key=([a-z0-9_]+)\]\.body",
            field_path,
        )
        sections = draft.get("sections")
        matches = (
            [
                section
                for section in sections
                if isinstance(section, dict)
                and section.get("key") == section_match.group(1)
            ]
            if section_match and isinstance(sections, list)
            else []
        )
        if len(matches) != 1:
            raise PublicCopyManifestError(
                f"Correction {entry_id} expected-draft section does not resolve exactly once."
            )
        value = matches[0].get("body")
    if not isinstance(value, str):
        raise PublicCopyManifestError(
            f"Correction {entry_id} expected-draft scalar is invalid."
        )
    return value


def _top_level_field(field_path: str) -> str:
    return field_path.removeprefix("draft_content.").split(".", 1)[0].split("[", 1)[0]


def _normalized_fingerprint(value: str | None) -> str:
    normalized = " ".join(
        unicodedata.normalize("NFKC", value or "").casefold().split()
    )
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _required_sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise PublicCopyManifestError(f"{field} must be a lowercase SHA-256 value.")
    return value


def _validate_execution_source_snapshot(
    manifest: dict[str, Any],
    *,
    source_root: str | Path | None,
) -> Path:
    snapshot = _object(
        manifest.get("execution_source_snapshot"),
        field="execution_source_snapshot",
    )
    expected_keys = {
        "snapshot_role",
        "source_root_contract",
        "modules",
        "canonical_module_list_sha256",
        "git_baseline_commit",
        "production_freeze_ack",
        "performance_local_v5_layout_contract",
        "customer_data",
    }
    if set(snapshot) != expected_keys:
        raise PublicCopyManifestError(
            "Execution-source snapshot has an unknown or incomplete contract."
        )
    if (
        snapshot.get("snapshot_role")
        != PUBLIC_COPY_EXECUTION_SOURCE_SNAPSHOT_ROLE
        or snapshot.get("git_baseline_commit")
        != PUBLIC_COPY_GIT_BASELINE_COMMIT
        or snapshot.get("production_freeze_ack")
        != "public-copy-production-source-frozen-v1"
        or snapshot.get("customer_data") is not False
    ):
        raise PublicCopyManifestError(
            "Execution-source snapshot identity is invalid."
        )
    contract = _object(
        snapshot.get("source_root_contract"),
        field="execution_source_snapshot.source_root_contract",
    )
    modules = snapshot.get("modules")
    if not isinstance(modules, list) or not modules:
        raise PublicCopyManifestError(
            "Execution-source snapshot has no bound modules."
        )
    paths: list[str] = []
    observed_rows: list[dict[str, Any]] = []
    for index, value in enumerate(modules):
        row = _object(
            value,
            field=f"execution_source_snapshot.modules[{index}]",
        )
        if set(row) != {"path", "size_bytes", "sha256"}:
            raise PublicCopyManifestError(
                "Execution-source module has an unknown or incomplete contract."
            )
        relative = row.get("path")
        if (
            not isinstance(relative, str)
            or not relative
            or relative != relative.strip()
            or "\\" in relative
            or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or not relative.startswith(("backend/", "frontend/"))
        ):
            raise PublicCopyManifestError(
                "Execution-source module path is unsafe."
            )
        size_bytes = row.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes <= 0:
            raise PublicCopyManifestError(
                "Execution-source module size is invalid."
            )
        digest = _required_sha256(
            row.get("sha256"),
            field=f"execution_source_snapshot.modules[{index}].sha256",
        )
        paths.append(relative)
        observed_rows.append(
            {"path": relative, "size_bytes": size_bytes, "sha256": digest}
        )
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PublicCopyManifestError(
            "Execution-source modules must have unique lexicographic paths."
        )
    layout_contract = _object(
        snapshot.get("performance_local_v5_layout_contract"),
        field="execution_source_snapshot.performance_local_v5_layout_contract",
    )
    expected_layout_contract = {
        "path": _PERFORMANCE_LOCAL_V5_LAYOUT_PATH,
        "mutation_allowed": False,
        "must_equal_pre_repair_source_baseline": True,
    }
    if layout_contract != expected_layout_contract:
        raise PublicCopyManifestError(
            "Performance Local V5 layout contract is invalid."
        )
    layout_rows = [
        row for row in observed_rows if row["path"] == layout_contract["path"]
    ]
    if layout_rows != [
        {
            "path": _PERFORMANCE_LOCAL_V5_LAYOUT_PATH,
            "size_bytes": _PERFORMANCE_LOCAL_V5_LAYOUT_SIZE_BYTES,
            "sha256": _PERFORMANCE_LOCAL_V5_LAYOUT_SHA256,
        }
    ]:
        raise PublicCopyManifestError(
            "Performance Local V5 layout module does not match its immutable pre-repair identity."
        )
    expected_contract = {
        "root": "repository_root",
        "path_format": "repo_relative_posix",
        "allowed_paths": paths,
        "ordering": "lexicographic_path",
        "regular_files_only": True,
        "reject_symlinks": True,
        "hash_algorithm": "sha256-bytes",
    }
    if contract != expected_contract:
        raise PublicCopyManifestError(
            "Execution-source root contract is invalid."
        )
    if canonical_json_sha256(observed_rows) != _required_sha256(
        snapshot.get("canonical_module_list_sha256"),
        field="execution_source_snapshot.canonical_module_list_sha256",
    ):
        raise PublicCopyManifestError(
            "Execution-source canonical module-list hash is invalid."
        )
    root = _source_root(source_root)
    if _is_link_or_reparse(root.absolute()):
        raise PublicCopyManifestError(
            "Execution source repository root may not be a symlink or reparse point."
        )
    root_resolved = root.resolve(strict=True)
    discovered_paths = _discover_execution_source_paths(root_resolved)
    if paths != discovered_paths:
        raise PublicCopyManifestError(
            "Execution-source modules are not the exhaustive frozen source discovery."
        )
    for row in observed_rows:
        _reject_execution_link_components(root_resolved, row["path"])
        candidate = root_resolved.joinpath(*row["path"].split("/"))
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise PublicCopyManifestError(
                f"Execution-source module does not exist: {row['path']}."
            ) from exc
        try:
            resolved.relative_to(root_resolved)
        except ValueError as exc:
            raise PublicCopyManifestError(
                "Execution-source module escapes the repository root."
            ) from exc
        if _is_link_or_reparse(candidate) or not resolved.is_file():
            raise PublicCopyManifestError(
                f"Execution-source module is not a regular non-symlink file: {row['path']}."
            )
        body = resolved.read_bytes()
        if len(body) != row["size_bytes"] or hashlib.sha256(body).hexdigest() != row["sha256"]:
            raise PublicCopyManifestError(
                f"Execution-source module bytes drifted: {row['path']}."
            )
    if _discover_execution_source_paths(root_resolved) != discovered_paths:
        raise PublicCopyManifestError(
            "Execution-source discovery changed during validation."
        )
    return root_resolved


def _discover_execution_source_paths(root: Path) -> list[str]:
    discovered: list[str] = []
    for relative_root in ("backend/app", "backend/scripts"):
        base = root.joinpath(*relative_root.split("/"))
        if (
            not base.is_dir()
            or _is_link_or_reparse(base)
        ):
            raise PublicCopyManifestError(
                f"Execution-source discovery root is missing or unsafe: {relative_root}."
            )
        for candidate in base.rglob("*"):
            relative = candidate.relative_to(root).as_posix()
            _reject_execution_link_components(root, relative)
            if _is_link_or_reparse(candidate):
                raise PublicCopyManifestError(
                    f"Execution-source discovery encountered a symlink or reparse point: {relative}."
                )
            if candidate.is_file() and candidate.suffix == ".py":
                discovered.append(relative)
    layout = root.joinpath(*_PERFORMANCE_LOCAL_V5_LAYOUT_PATH.split("/"))
    _reject_execution_link_components(root, _PERFORMANCE_LOCAL_V5_LAYOUT_PATH)
    if not layout.is_file() or _is_link_or_reparse(layout):
        raise PublicCopyManifestError(
            "Performance Local V5 layout execution source is missing or unsafe."
        )
    discovered.append(_PERFORMANCE_LOCAL_V5_LAYOUT_PATH)
    result = sorted(discovered)
    if len(result) != len(set(result)):
        raise PublicCopyManifestError(
            "Execution-source discovery produced duplicate module paths."
        )
    return result


def _reject_execution_link_components(root: Path, relative: str) -> None:
    current = root
    for part in relative.split("/"):
        current = current / part
        if _is_link_or_reparse(current):
            raise PublicCopyManifestError(
                "Execution-source path contains a symlink or reparse-point component: "
                f"{relative}."
            )


def _source_root(explicit: str | Path | None) -> Path:
    if explicit is not None:
        value = Path(explicit)
        if _is_link_or_reparse(value.absolute()) or not value.is_dir():
            raise PublicCopyManifestError(
                "Explicit execution source root is not a regular directory."
            )
        return value
    for candidate in Path(__file__).resolve().parents:
        if (
            candidate.joinpath("backend", "app", "services", "public_copy_manifest.py").is_file()
            and candidate.joinpath("frontend").is_dir()
        ):
            return candidate
    raise PublicCopyManifestError(
        "Execution source repository root could not be discovered."
    )


def _validate_operation_path(
    *,
    operation: str,
    field_path: Any,
    entry_id: str,
) -> None:
    if not isinstance(field_path, str) or field_path != field_path.strip():
        raise PublicCopyManifestError(
            f"Correction {entry_id} has an invalid field path."
        )
    scalar = re.fullmatch(
        r"draft_content\.(?:intro|meta_description|call_to_action)",
        field_path,
    ) or re.fullmatch(
        r"draft_content\.sections\[key=[a-z0-9_]+\]\.body",
        field_path,
    )
    omission = re.fullmatch(
        r"draft_content\.sections\[key=[a-z0-9_]+\]\.body"
        r"::exact_sentence\[knowledge_block_id=[1-9][0-9]*\]",
        field_path,
    )
    projection = re.fullmatch(
        r"draft_content\.public_destination_copy(?:"
        r"\[source_kind=internal_link_intent,source_record_id=[1-9][0-9]*\]"
        r"\.description)?",
        field_path,
    )
    valid = {
        "replace_exact_value": scalar is not None,
        "remove_exact_sentence": omission is not None,
        "add_destination_derived_public_projection": projection is not None,
    }[operation]
    if not valid:
        raise PublicCopyManifestError(
            f"Correction {entry_id} operation/field-path coupling is invalid."
        )


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PublicCopyManifestError(f"{field} must be a positive integer.")
    return value


def _nullable_positive_int(value: Any, *, field: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, field=field)


def _required_text(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise PublicCopyManifestError(f"{field} must be exact nonempty text.")
    return value


def _exact_keys(
    value: dict[str, Any],
    expected: set[str],
    *,
    field: str,
) -> None:
    if set(value) != expected:
        raise PublicCopyManifestError(
            f"{field} has an unknown or incomplete contract."
        )


def _is_link_or_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        if callable(is_junction) and is_junction():
            return True
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(
        attributes
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _object(value: Any, *, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PublicCopyManifestError(f"{field} must be an object.")
    return value
