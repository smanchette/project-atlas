from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
from typing import Any, Mapping

from sqlmodel import Session, select

from app.models import (
    GeneratedPageRevision,
    PageComposition,
    PageCompositionRevision,
)


MIGRATION_BACKFILL_SOURCE = "migration_0048_backfill"
MIGRATION_BACKFILL_ACTOR = "migration:20260820_0048"
COMPOSITION_REFRESH_SOURCE = "composition_refresh"
COMPOSITION_REFRESH_ACTOR = "atlas:composition_refresh"
OPERATOR_DECISION_SOURCE = "operator_decision"

REVISION_HASH_FIELDS = (
    "page_composition_id",
    "website_id",
    "site_plan_id",
    "planned_page_id",
    "generated_page_id",
    "generated_page_revision_id",
    "composition_version",
    "supersedes_revision_id",
    "supersedes_revision_hash",
    "lineage_kind",
    "content_hash",
    "generated_components",
    "operator_decisions",
    "source_snapshot",
    "source_hash",
    "generated_at",
    "decided_by",
    "decided_at",
    "recorded_at",
    "recorded_by",
    "record_source",
)


class PageCompositionHistoryError(ValueError):
    pass


def canonical_utc_timestamp(value: datetime) -> str:
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value
    return normalized.astimezone(UTC).isoformat()


def composition_content_hash(source_snapshot: Mapping[str, Any]) -> str:
    value = source_snapshot.get("draft_hash")
    if not _is_lower_sha256(value):
        raise PageCompositionHistoryError(
            "Page Composition source snapshot lacks an exact lowercase draft hash."
        )
    return value


def composition_revision_hash(values: Mapping[str, Any]) -> str:
    """Hash every immutable revision field except its database-generated row ID."""

    payload: dict[str, Any] = {}
    for field in REVISION_HASH_FIELDS:
        if field not in values:
            raise PageCompositionHistoryError(
                f"Page Composition revision hash input is missing {field}."
            )
        value = values[field]
        if field in {"generated_at", "recorded_at"}:
            if not isinstance(value, datetime):
                raise PageCompositionHistoryError(
                    f"Page Composition revision {field} must be a timestamp."
                )
            value = canonical_utc_timestamp(value)
        elif field == "decided_at" and value is not None:
            if not isinstance(value, datetime):
                raise PageCompositionHistoryError(
                    "Page Composition revision decided_at must be a timestamp or null."
                )
            value = canonical_utc_timestamp(value)
        payload[field] = value
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def canonical_payload_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def current_composition_revision(
    session: Session,
    composition: PageComposition,
    *,
    lock: bool = False,
) -> PageCompositionRevision:
    if composition.id is None:
        raise PageCompositionHistoryError(
            "Page Composition must be persisted before history can resolve."
        )
    statement = select(PageCompositionRevision).where(
        PageCompositionRevision.page_composition_id == composition.id,
        PageCompositionRevision.composition_version
        == composition.composition_version,
        PageCompositionRevision.source_hash == composition.source_hash,
    )
    if lock:
        statement = statement.with_for_update()
    rows = list(session.exec(statement).all())
    if len(rows) != 1:
        raise PageCompositionHistoryError(
            "Page Composition does not resolve one exact current revision."
        )
    revision = rows[0]
    stream = validate_composition_stream(session, composition, lock=lock)
    if stream[-1].id != revision.id:
        raise PageCompositionHistoryError(
            "Page Composition current revision is not the unique lineage tip."
        )
    _require_head_mirror(composition, revision)
    return revision


def read_composition_revision(
    session: Session,
    composition_id: int,
    composition_version: int,
    *,
    generated_page_id: int | None = None,
    website_id: int | None = None,
) -> PageCompositionRevision:
    composition = session.get(PageComposition, composition_id)
    if composition is None:
        raise PageCompositionHistoryError("Page Composition was not found.")
    if generated_page_id is not None and composition.generated_page_id != generated_page_id:
        raise PageCompositionHistoryError(
            "Historical composition crosses the requested Generated Page boundary."
        )
    if website_id is not None and composition.website_id != website_id:
        raise PageCompositionHistoryError(
            "Historical composition crosses the requested Website boundary."
        )
    rows = [
        revision
        for revision in validate_composition_stream(session, composition)
        if revision.composition_version == composition_version
    ]
    if len(rows) != 1:
        raise PageCompositionHistoryError(
            "Historical composition identity does not resolve exactly once."
        )
    revision = rows[0]
    return revision


def list_composition_revisions(
    session: Session,
    composition_id: int,
) -> list[PageCompositionRevision]:
    composition = session.get(PageComposition, composition_id)
    if composition is None:
        raise PageCompositionHistoryError("Page Composition was not found.")
    return validate_composition_stream(session, composition)


def composition_revision_read_values(
    session: Session,
    revision: PageCompositionRevision,
) -> dict[str, Any]:
    composition = session.get(PageComposition, revision.page_composition_id)
    if composition is None:
        raise PageCompositionHistoryError(
            "Page Composition revision has no owning composition."
        )
    validate_composition_revision(session, revision, composition=composition)
    is_head = (
        revision.composition_version == composition.composition_version
        and revision.source_hash == composition.source_hash
    )
    if is_head:
        _require_head_mirror(composition, revision)
    return {
        **revision.model_dump(mode="python"),
        "is_head_revision": is_head,
        "head_status": composition.status if is_head else None,
    }


def create_initial_composition_revision(
    session: Session,
    composition: PageComposition,
    *,
    recorded_by: str = COMPOSITION_REFRESH_ACTOR,
    record_source: str = COMPOSITION_REFRESH_SOURCE,
    recorded_at: datetime | None = None,
    lineage_kind: str = "initial",
) -> PageCompositionRevision:
    if composition.id is None:
        session.flush()
    if composition.id is None:
        raise PageCompositionHistoryError(
            "Page Composition identity was not assigned."
        )
    if session.exec(
        select(PageCompositionRevision).where(
            PageCompositionRevision.page_composition_id == composition.id
        )
    ).first() is not None:
        raise PageCompositionHistoryError(
            "Initial Page Composition history already exists."
        )
    if lineage_kind not in {"initial", "legacy_root"}:
        raise PageCompositionHistoryError("Initial history has an invalid lineage kind.")
    if lineage_kind == "initial" and composition.composition_version != 1:
        raise PageCompositionHistoryError(
            "A non-v1 composition must begin with truthful legacy-root lineage."
        )
    return _insert_revision(
        session,
        composition,
        composition_version=composition.composition_version,
        generated_components=composition.generated_components,
        operator_decisions=composition.operator_decisions,
        source_snapshot=composition.source_snapshot,
        source_hash=composition.source_hash,
        generated_at=composition.generated_at,
        decided_by=composition.decided_by,
        decided_at=composition.decided_at,
        predecessor=None,
        lineage_kind=lineage_kind,
        recorded_at=recorded_at or datetime.now(UTC),
        recorded_by=recorded_by,
        record_source=record_source,
    )


def advance_composition_revision(
    session: Session,
    composition: PageComposition,
    *,
    generated_components: list[dict[str, Any]],
    operator_decisions: list[dict[str, Any]],
    source_snapshot: dict[str, Any],
    source_hash: str,
    generated_at: datetime,
    decided_by: str | None,
    decided_at: datetime | None,
    recorded_by: str = COMPOSITION_REFRESH_ACTOR,
    record_source: str = COMPOSITION_REFRESH_SOURCE,
    recorded_at: datetime | None = None,
    head_updated_at: datetime | None = None,
) -> PageCompositionRevision:
    predecessor = current_composition_revision(session, composition, lock=True)
    revision = _insert_revision(
        session,
        composition,
        composition_version=composition.composition_version + 1,
        generated_components=generated_components,
        operator_decisions=operator_decisions,
        source_snapshot=source_snapshot,
        source_hash=source_hash,
        generated_at=generated_at,
        decided_by=decided_by,
        decided_at=decided_at,
        predecessor=predecessor,
        lineage_kind="successor",
        recorded_at=recorded_at or datetime.now(UTC),
        recorded_by=recorded_by,
        record_source=record_source,
    )
    composition.generated_components = deepcopy(generated_components)
    composition.operator_decisions = deepcopy(operator_decisions)
    composition.source_snapshot = deepcopy(source_snapshot)
    composition.source_hash = source_hash
    composition.status = "current"
    composition.generated_at = generated_at
    composition.decided_by = decided_by
    composition.decided_at = decided_at
    composition.composition_version = revision.composition_version
    composition.updated_at = head_updated_at or generated_at
    session.add(composition)
    session.flush()
    _require_head_mirror(composition, revision)
    return revision


def validate_composition_revision(
    session: Session,
    revision: PageCompositionRevision,
    *,
    composition: PageComposition | None = None,
) -> None:
    composition = composition or session.get(
        PageComposition, revision.page_composition_id
    )
    if composition is None:
        raise PageCompositionHistoryError(
            "Page Composition revision has no owning composition."
        )
    if (
        revision.website_id != composition.website_id
        or revision.site_plan_id != composition.site_plan_id
        or revision.planned_page_id != composition.planned_page_id
        or revision.generated_page_id != composition.generated_page_id
    ):
        raise PageCompositionHistoryError(
            "Page Composition revision crosses its exact ownership boundary."
        )
    if revision.source_hash != canonical_payload_hash(revision.source_snapshot):
        raise PageCompositionHistoryError(
            "Page Composition revision source hash does not match its snapshot."
        )
    if revision.content_hash != composition_content_hash(revision.source_snapshot):
        raise PageCompositionHistoryError(
            "Page Composition revision content identity does not match its snapshot."
        )
    values = revision.model_dump(mode="python")
    if revision.revision_hash != composition_revision_hash(values):
        raise PageCompositionHistoryError(
            "Page Composition revision immutable hash does not match its evidence."
        )
    expected_generated_revision_id = _latest_generated_page_revision_id(
        session,
        revision.generated_page_id,
        revision.content_hash,
        generated_at=revision.generated_at,
    )
    if revision.generated_page_revision_id != expected_generated_revision_id:
        raise PageCompositionHistoryError(
            "Page Composition revision loses its exact Generated Page revision binding."
        )


def validate_composition_lineage(
    session: Session,
    revision: PageCompositionRevision,
    *,
    composition: PageComposition | None = None,
) -> None:
    composition = composition or session.get(
        PageComposition, revision.page_composition_id
    )
    if composition is None:
        raise PageCompositionHistoryError(
            "Page Composition revision has no owning composition."
        )
    seen: set[int] = set()
    current = revision
    while True:
        if current.id is None or current.id in seen:
            raise PageCompositionHistoryError(
                "Page Composition revision lineage is cyclic or unpersisted."
            )
        seen.add(current.id)
        validate_composition_revision(session, current, composition=composition)
        if current.supersedes_revision_id is None:
            if current.lineage_kind not in {"initial", "legacy_root"}:
                raise PageCompositionHistoryError(
                    "Page Composition revision lineage has an invalid root."
                )
            return
        predecessor = session.get(
            PageCompositionRevision, current.supersedes_revision_id
        )
        if (
            predecessor is None
            or predecessor.page_composition_id != current.page_composition_id
            or predecessor.composition_version != current.composition_version - 1
            or predecessor.revision_hash != current.supersedes_revision_hash
            or current.lineage_kind != "successor"
        ):
            raise PageCompositionHistoryError(
                "Page Composition revision predecessor lineage is invalid."
            )
        current = predecessor


def validate_composition_stream(
    session: Session,
    composition: PageComposition,
    *,
    lock: bool = False,
) -> list[PageCompositionRevision]:
    """Validate one complete, unbranched stream and its exact materialized tip."""

    if composition.id is None:
        raise PageCompositionHistoryError(
            "Page Composition must be persisted before history can resolve."
        )
    statement = (
        select(PageCompositionRevision)
        .where(PageCompositionRevision.page_composition_id == composition.id)
        .order_by(
            PageCompositionRevision.composition_version,
            PageCompositionRevision.id,
        )
    )
    if lock:
        statement = statement.with_for_update()
    revisions = list(session.exec(statement).all())
    if not revisions:
        raise PageCompositionHistoryError(
            "Page Composition has no immutable revision history."
        )

    seen_ids: set[int] = set()
    seen_versions: set[int] = set()
    seen_hashes: set[str] = set()
    predecessor: PageCompositionRevision | None = None
    for revision in revisions:
        if (
            revision.id is None
            or revision.id in seen_ids
            or revision.composition_version in seen_versions
            or revision.revision_hash in seen_hashes
        ):
            raise PageCompositionHistoryError(
                "Page Composition revision stream has duplicate immutable identity."
            )
        seen_ids.add(revision.id)
        seen_versions.add(revision.composition_version)
        seen_hashes.add(revision.revision_hash)
        validate_composition_revision(session, revision, composition=composition)
        if predecessor is None:
            if (
                revision.lineage_kind not in {"initial", "legacy_root"}
                or revision.supersedes_revision_id is not None
                or revision.supersedes_revision_hash is not None
                or (
                    revision.lineage_kind == "initial"
                    and revision.composition_version != 1
                )
            ):
                raise PageCompositionHistoryError(
                    "Page Composition revision stream has an invalid root."
                )
        elif (
            revision.lineage_kind != "successor"
            or revision.composition_version != predecessor.composition_version + 1
            or revision.supersedes_revision_id != predecessor.id
            or revision.supersedes_revision_hash != predecessor.revision_hash
        ):
            raise PageCompositionHistoryError(
                "Page Composition revision stream is branched, gapped, or disconnected."
            )
        predecessor = revision

    tip = revisions[-1]
    if (
        tip.composition_version != composition.composition_version
        or tip.source_hash != composition.source_hash
    ):
        raise PageCompositionHistoryError(
            "Page Composition materialized head is not the unique lineage tip."
        )
    _require_head_mirror(composition, tip)
    return revisions


def _insert_revision(
    session: Session,
    composition: PageComposition,
    *,
    composition_version: int,
    generated_components: list[dict[str, Any]],
    operator_decisions: list[dict[str, Any]],
    source_snapshot: dict[str, Any],
    source_hash: str,
    generated_at: datetime,
    decided_by: str | None,
    decided_at: datetime | None,
    predecessor: PageCompositionRevision | None,
    lineage_kind: str,
    recorded_at: datetime,
    recorded_by: str,
    record_source: str,
) -> PageCompositionRevision:
    if composition.id is None:
        raise PageCompositionHistoryError(
            "Page Composition must be persisted before a revision is recorded."
        )
    actor = recorded_by.strip()
    source = record_source.strip()
    if not actor or not source:
        raise PageCompositionHistoryError(
            "Page Composition revision actor and source are required."
        )
    if source_hash != canonical_payload_hash(source_snapshot):
        raise PageCompositionHistoryError(
            "Candidate Page Composition source hash does not match its snapshot."
        )
    content_hash = composition_content_hash(source_snapshot)
    generated_page_revision_id = _latest_generated_page_revision_id(
        session,
        composition.generated_page_id,
        content_hash,
        generated_at=generated_at,
    )
    values: dict[str, Any] = {
        "page_composition_id": composition.id,
        "website_id": composition.website_id,
        "site_plan_id": composition.site_plan_id,
        "planned_page_id": composition.planned_page_id,
        "generated_page_id": composition.generated_page_id,
        "generated_page_revision_id": generated_page_revision_id,
        "composition_version": composition_version,
        "supersedes_revision_id": predecessor.id if predecessor else None,
        "supersedes_revision_hash": predecessor.revision_hash if predecessor else None,
        "lineage_kind": lineage_kind,
        "content_hash": content_hash,
        "generated_components": deepcopy(generated_components),
        "operator_decisions": deepcopy(operator_decisions),
        "source_snapshot": deepcopy(source_snapshot),
        "source_hash": source_hash,
        "generated_at": generated_at,
        "decided_by": decided_by,
        "decided_at": decided_at,
        "recorded_at": recorded_at,
        "recorded_by": actor,
        "record_source": source,
    }
    revision = PageCompositionRevision(
        **values,
        revision_hash=composition_revision_hash(values),
    )
    session.add(revision)
    session.flush()
    validate_composition_revision(session, revision, composition=composition)
    return revision


def _latest_generated_page_revision_id(
    session: Session,
    generated_page_id: int,
    content_hash: str,
    *,
    generated_at: datetime,
) -> int | None:
    latest = session.exec(
        select(GeneratedPageRevision)
        .where(
            GeneratedPageRevision.generated_page_id == generated_page_id,
            GeneratedPageRevision.created_at <= generated_at,
        )
        .order_by(
            GeneratedPageRevision.created_at.desc(),
            GeneratedPageRevision.id.desc(),
        )
    ).first()
    if latest is None:
        return None
    if latest.draft_hash_after != content_hash:
        raise PageCompositionHistoryError(
            "Generated Page content is not represented by its latest revision."
        )
    return latest.id


def _require_head_mirror(
    composition: PageComposition,
    revision: PageCompositionRevision,
) -> None:
    fields = (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "composition_version",
        "generated_components",
        "operator_decisions",
        "source_snapshot",
        "source_hash",
        "generated_at",
        "decided_by",
        "decided_at",
    )
    for field in fields:
        left = getattr(composition, field)
        right = getattr(revision, field)
        if isinstance(left, datetime) and isinstance(right, datetime):
            if canonical_utc_timestamp(left) == canonical_utc_timestamp(right):
                continue
        elif left == right:
            continue
        raise PageCompositionHistoryError(
            f"Page Composition head diverges from revision field {field}."
        )


def _is_lower_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )
