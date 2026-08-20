from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.page_composition_history import (
    REVISION_HASH_FIELDS,
    PageCompositionHistoryError,
    canonical_payload_hash,
    composition_content_hash,
    composition_revision_hash,
)
from app.services.page_qa import qa_result_record_hash


EVIDENCE_SCHEMA = "project-atlas-page-composition-history-evidence"
EVIDENCE_VERSION = "1"
EVIDENCE_RECORDED_BY = "atlas:legacy_composition_recovery"
EVIDENCE_RECORD_SOURCE = "legacy_history_evidence_v1"

QA_RESULT_HASH_FIELDS = (
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "latest_generated_page_revision_id",
    "content_hash",
    "source_hash",
    "page_composition_id",
    "composition_version",
    "composition_source_hash",
    "qa_algorithm_key",
    "qa_algorithm_version",
    "qa_ruleset_key",
    "qa_ruleset_version",
    "qa_ruleset_hash",
    "readiness_status",
    "passed_count",
    "warning_count",
    "failed_count",
    "check_payload",
    "evaluated_at",
)

_TOP_LEVEL_FIELDS = {
    "schema",
    "version",
    "created_at",
    "source_artifact",
    "records",
}
_SOURCE_ARTIFACT_FIELDS = {
    "app",
    "backup_version",
    "created_at",
    "sha256",
    "size_bytes",
}
_RECORD_FIELDS = {"revision", "qa_results", "record_hash"}
_REVISION_FIELDS = {*REVISION_HASH_FIELDS, "revision_hash"}
_QA_RESULT_FIELDS = {"id", *QA_RESULT_HASH_FIELDS, "result_hash"}


class PageCompositionHistoryEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class PageCompositionHistoryEvidence:
    path: Path
    sha256: str
    created_at: datetime
    source_artifact: dict[str, Any]
    records: tuple[dict[str, Any], ...]


def load_page_composition_history_evidence(
    evidence_path: str | Path,
    expected_sha256: str,
) -> PageCompositionHistoryEvidence:
    """Load and validate one explicitly selected, caller-sealed recovery sidecar."""

    if not _is_lower_sha256(expected_sha256):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence SHA256 must be an exact lowercase digest."
        )
    path = Path(evidence_path)
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise PageCompositionHistoryEvidenceError(
            f"Page Composition history evidence file not found: {path}"
        ) from exc
    except OSError as exc:
        raise PageCompositionHistoryEvidenceError(
            f"Page Composition history evidence file could not be read: {path}"
        ) from exc

    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence file does not match the caller-supplied SHA256."
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence is not valid UTF-8 JSON."
        ) from exc

    if not isinstance(payload, dict) or set(payload) != _TOP_LEVEL_FIELDS:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence does not match the exact top-level contract."
        )
    if (
        payload.get("schema") != EVIDENCE_SCHEMA
        or payload.get("version") != EVIDENCE_VERSION
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence schema or version is unsupported."
        )
    created_at = _timestamp(
        payload.get("created_at"),
        "evidence.created_at",
        require_utc=True,
    )
    source_artifact = payload.get("source_artifact")
    if not isinstance(source_artifact, dict) or set(source_artifact) != (
        _SOURCE_ARTIFACT_FIELDS
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence source artifact is malformed."
        )
    _validate_source_artifact(source_artifact, evidence_created_at=created_at)

    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence must contain at least one record."
        )

    observed_identities: set[tuple[int, int, str]] = set()
    observed_qa_ids: set[int] = set()
    validated_records: list[dict[str, Any]] = []
    source_created_at = _timestamp(
        source_artifact["created_at"],
        "evidence.source_artifact.created_at",
        require_utc=True,
    )
    for record in records:
        identity, qa_ids = _validate_record(
            record,
            evidence_created_at=created_at,
            source_created_at=source_created_at,
        )
        if identity in observed_identities:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence duplicates a recovered revision identity."
            )
        duplicate_qa_ids = observed_qa_ids.intersection(qa_ids)
        if duplicate_qa_ids:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence duplicates a required QA result."
            )
        observed_identities.add(identity)
        observed_qa_ids.update(qa_ids)
        validated_records.append(record)

    if [
        (
            record["revision"]["page_composition_id"],
            record["revision"]["composition_version"],
            record["revision"]["source_hash"],
        )
        for record in validated_records
    ] != sorted(observed_identities):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence records must be sorted by exact revision identity."
        )

    return PageCompositionHistoryEvidence(
        path=path.resolve(),
        sha256=observed_sha256,
        created_at=created_at,
        source_artifact=source_artifact,
        records=tuple(validated_records),
    )


def stable_qa_result_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Return the immutable QA fields carried by the evidence contract."""

    return {
        "id": record.get("id"),
        **{field: record.get(field) for field in QA_RESULT_HASH_FIELDS},
        "result_hash": record.get("result_hash"),
    }


def _validate_source_artifact(
    value: dict[str, Any],
    *,
    evidence_created_at: datetime,
) -> None:
    if value.get("app") != "Project Atlas":
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence source app is invalid."
        )
    backup_version = value.get("backup_version")
    if not isinstance(backup_version, str) or not _is_pre_history_backup_version(
        backup_version
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence must identify a pre-0.59 source backup."
        )
    source_created_at = _timestamp(
        value.get("created_at"),
        "evidence.source_artifact.created_at",
        require_utc=True,
    )
    if source_created_at > evidence_created_at:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence was sealed before its source artifact existed."
        )
    if not _is_lower_sha256(value.get("sha256")):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence source artifact SHA256 is invalid."
        )
    size_bytes = value.get("size_bytes")
    if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 1:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence source artifact size is invalid."
        )


def _validate_record(
    value: object,
    *,
    evidence_created_at: datetime,
    source_created_at: datetime,
) -> tuple[tuple[int, int, str], set[int]]:
    if not isinstance(value, dict) or set(value) != _RECORD_FIELDS:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence record is malformed."
        )
    revision = value.get("revision")
    qa_results = value.get("qa_results")
    if not isinstance(revision, dict) or set(revision) != _REVISION_FIELDS:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision does not match the exact field contract."
        )
    if not isinstance(qa_results, list) or not qa_results:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision must name its required QA results."
        )
    _validate_revision(
        revision,
        evidence_created_at=evidence_created_at,
        source_created_at=source_created_at,
    )

    qa_ids: set[int] = set()
    for qa_result in qa_results:
        _validate_qa_result(qa_result, revision=revision)
        qa_id = qa_result["id"]
        if qa_id in qa_ids:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence record duplicates a QA result."
            )
        qa_ids.add(qa_id)
    if [qa_result["id"] for qa_result in qa_results] != sorted(qa_ids):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA results must be sorted by identity."
        )

    expected_record_hash = canonical_payload_hash(
        {
            "revision": revision,
            "qa_results": sorted(qa_results, key=lambda item: item["id"]),
        }
    )
    if value.get("record_hash") != expected_record_hash:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence record hash does not match its payload."
        )
    return (
        revision["page_composition_id"],
        revision["composition_version"],
        revision["source_hash"],
    ), qa_ids


def _validate_revision(
    revision: dict[str, Any],
    *,
    evidence_created_at: datetime,
    source_created_at: datetime,
) -> None:
    for field in (
        "page_composition_id",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "composition_version",
    ):
        if not _is_positive_int(revision.get(field)):
            raise PageCompositionHistoryEvidenceError(
                f"Page Composition history evidence revision has invalid {field}."
            )
    generated_revision_id = revision.get("generated_page_revision_id")
    if generated_revision_id is not None and not _is_positive_int(
        generated_revision_id
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision has an invalid Generated Page revision identity."
        )
    if (
        revision.get("supersedes_revision_id") is not None
        or revision.get("supersedes_revision_hash") is not None
        or revision.get("lineage_kind") != "legacy_root"
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence v1 revision must be a predecessor-free legacy root."
        )
    if (
        not isinstance(revision.get("generated_components"), list)
        or not all(
            isinstance(item, dict) for item in revision["generated_components"]
        )
        or not isinstance(revision.get("operator_decisions"), list)
        or not all(
            isinstance(item, dict) for item in revision["operator_decisions"]
        )
        or not isinstance(revision.get("source_snapshot"), dict)
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision payload is malformed."
        )
    for field in (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
    ):
        if revision["source_snapshot"].get(field) != revision[field]:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence revision source snapshot crosses its exact scope."
            )
    if revision.get("source_hash") != canonical_payload_hash(
        revision["source_snapshot"]
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision source hash is invalid."
        )
    try:
        expected_content_hash = composition_content_hash(
            revision["source_snapshot"]
        )
    except PageCompositionHistoryError as exc:
        raise PageCompositionHistoryEvidenceError(str(exc)) from exc
    if revision.get("content_hash") != expected_content_hash:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision content hash is invalid."
        )
    if (
        revision.get("recorded_by") != EVIDENCE_RECORDED_BY
        or revision.get("record_source") != EVIDENCE_RECORD_SOURCE
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision recovery provenance is invalid."
        )

    decided_by = revision.get("decided_by")
    decided_at_value = revision.get("decided_at")
    if decided_by is not None and (
        not isinstance(decided_by, str)
        or not decided_by
        or decided_by != decided_by.strip()
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision decision provenance is malformed."
        )

    generated_at = _timestamp(
        revision.get("generated_at"),
        "evidence.revision.generated_at",
    )
    recorded_at = _timestamp(
        revision.get("recorded_at"),
        "evidence.revision.recorded_at",
    )
    decided_at = (
        _timestamp(
            decided_at_value,
            "evidence.revision.decided_at",
        )
        if decided_at_value is not None
        else None
    )
    if _comparable(recorded_at) != _comparable(generated_at):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence legacy root must reuse its exact derivation instant."
        )
    if (
        _comparable(recorded_at) > _comparable(source_created_at)
        or _comparable(recorded_at) > _comparable(evidence_created_at)
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision postdates its provenance."
        )
    hash_values = {
        **revision,
        "generated_at": generated_at,
        "decided_at": decided_at,
        "recorded_at": recorded_at,
    }
    try:
        expected_revision_hash = composition_revision_hash(hash_values)
    except PageCompositionHistoryError as exc:
        raise PageCompositionHistoryEvidenceError(str(exc)) from exc
    if (
        not _is_lower_sha256(revision.get("revision_hash"))
        or revision["revision_hash"] != expected_revision_hash
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence revision immutable hash is invalid."
        )


def _validate_qa_result(
    qa_result: object,
    *,
    revision: dict[str, Any],
) -> None:
    if not isinstance(qa_result, dict) or set(qa_result) != _QA_RESULT_FIELDS:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA result does not match the exact stable field contract."
        )
    if not _is_positive_int(qa_result.get("id")):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA result identity is invalid."
        )
    for field in (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "page_composition_id",
        "composition_version",
    ):
        if not _is_positive_int(qa_result.get(field)):
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence QA result scope identity is invalid."
            )
        if qa_result.get(field) != revision.get(field):
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence QA result crosses its recovered revision scope."
            )
    generated_revision_id = qa_result.get("latest_generated_page_revision_id")
    if generated_revision_id is not None and not _is_positive_int(
        generated_revision_id
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA Generated Page revision identity is invalid."
        )
    if (
        generated_revision_id != revision.get("generated_page_revision_id")
        or qa_result.get("content_hash") != revision.get("content_hash")
        or qa_result.get("composition_source_hash")
        != revision.get("source_hash")
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA result loses its exact content, revision, or composition binding."
        )
    for field in (
        "content_hash",
        "source_hash",
        "composition_source_hash",
        "qa_ruleset_hash",
        "result_hash",
    ):
        if not _is_lower_sha256(qa_result.get(field)):
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence QA result hash is malformed."
            )
    for field in (
        "qa_algorithm_key",
        "qa_algorithm_version",
        "qa_ruleset_key",
        "qa_ruleset_version",
    ):
        value = qa_result.get(field)
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
        ):
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence QA provenance is malformed."
            )
    if qa_result.get("readiness_status") not in {
        "ready",
        "needs_review",
        "blocked",
    }:
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA readiness is invalid."
        )
    for field in ("passed_count", "warning_count", "failed_count"):
        value = qa_result.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence QA counts are invalid."
            )
    check_payload = qa_result.get("check_payload")
    if not isinstance(check_payload, list) or not all(
        isinstance(item, dict) for item in check_payload
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA checks are malformed."
        )
    evaluated_at = _timestamp(
        qa_result.get("evaluated_at"),
        "evidence.qa_results.evaluated_at",
    )
    hash_values = {**qa_result, "evaluated_at": evaluated_at}
    if (
        qa_result["result_hash"] != qa_result_record_hash(hash_values)
    ):
        raise PageCompositionHistoryEvidenceError(
            "Page Composition history evidence QA result hash is invalid."
        )


def _timestamp(
    value: object,
    field: str,
    *,
    require_utc: bool = False,
) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise PageCompositionHistoryEvidenceError(
            f"Page Composition history {field} timestamp is invalid."
        )
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise PageCompositionHistoryEvidenceError(
            f"Page Composition history {field} timestamp is invalid."
        ) from exc
    if require_utc and (
        parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0
    ):
        raise PageCompositionHistoryEvidenceError(
            f"Page Composition history {field} timestamp must be explicit UTC."
        )
    return parsed


def _comparable(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_lower_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_pre_history_backup_version(value: str) -> bool:
    try:
        major, minor = value.split(".", maxsplit=1)
        version = (int(major), int(minor))
    except (TypeError, ValueError):
        return False
    return (0, 49) <= version < (0, 59)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PageCompositionHistoryEvidenceError(
                "Page Composition history evidence contains a duplicate JSON key."
            )
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise PageCompositionHistoryEvidenceError(
        f"Page Composition history evidence contains invalid JSON constant {value}."
    )
