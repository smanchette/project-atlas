import argparse
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, SQLModel, select

from app.db.session import create_db_and_tables, engine
from app.models import (
    ApprovalAudit,
    Business,
    City,
    County,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    KnowledgeBlock,
    PageImageAssignment,
    Service,
    Setting,
    WordPressDraftAudit,
    WordPressMediaSyncAudit,
    WordPressPublishAudit,
    WordPressQualityReview,
)

APP_NAME = "Project Atlas"
BACKUP_VERSION = "0.29"
SUPPORTED_BACKUP_VERSIONS = {
    "0.4",
    "0.5",
    "0.7",
    "0.8",
    "0.9",
    "0.10",
    "0.11",
    "0.12",
    "0.13",
    "0.17",
    "0.27",
    "0.28",
    "0.29",
}
BACKEND_ROOT = Path(__file__).resolve().parents[2]
BACKUP_DIR = BACKEND_ROOT / "backups"
SENSITIVE_SETTING_MARKERS = (
    "api_key",
    "application_password",
    "password",
    "private_key",
    "secret",
    "token",
)

BACKUP_MODELS: dict[str, type[SQLModel]] = {
    "businesses": Business,
    "services": Service,
    "counties": County,
    "cities": City,
    "generated_pages": GeneratedPage,
    "approval_audits": ApprovalAudit,
    "page_revisions": GeneratedPageRevision,
    "wordpress_draft_audits": WordPressDraftAudit,
    "wordpress_publish_audits": WordPressPublishAudit,
    "wordpress_media_sync_audits": WordPressMediaSyncAudit,
    "wordpress_quality_reviews": WordPressQualityReview,
    "image_metadata": ImageMetadata,
    "page_image_assignments": PageImageAssignment,
    "settings": Setting,
    "knowledge_blocks": KnowledgeBlock,
}


class BackupValidationError(ValueError):
    pass


def export_backup(
    session: Session,
    *,
    backup_dir: Path | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    destination = backup_dir or BACKUP_DIR
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)
    backup_path = _available_backup_path(destination, timestamp)

    data = {}
    for group, model in BACKUP_MODELS.items():
        records = session.exec(select(model).order_by(model.id)).all()
        if group == "settings":
            records = [
                record
                for record in records
                if not is_sensitive_setting_key(record.setting_key)
            ]
        data[group] = [record.model_dump(mode="json") for record in records]
    table_counts = {group: len(records) for group, records in data.items()}
    payload = {
        "metadata": {
            "app": APP_NAME,
            "version": BACKUP_VERSION,
            "created_at": timestamp.isoformat(),
            "table_counts": table_counts,
        },
        "data": data,
    }
    backup_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    return {
        "file_name": backup_path.name,
        "path": str(backup_path),
        "created_at": timestamp.isoformat(),
        "table_counts": table_counts,
        "status": "created",
    }


def list_backups(*, backup_dir: Path | None = None) -> list[dict[str, Any]]:
    destination = backup_dir or BACKUP_DIR
    if not destination.exists():
        return []

    backups: list[dict[str, Any]] = []
    for backup_path in sorted(destination.glob("atlas-backup-*.json"), reverse=True):
        try:
            payload = load_backup(backup_path)
            metadata = payload["metadata"]
            backups.append(
                {
                    "file_name": backup_path.name,
                    "created_at": metadata["created_at"],
                    "table_counts": metadata["table_counts"],
                    "status": "ready",
                }
            )
        except (BackupValidationError, OSError) as exc:
            backups.append(
                {
                    "file_name": backup_path.name,
                    "created_at": None,
                    "table_counts": {},
                    "status": "invalid",
                    "error": str(exc),
                }
            )
    return backups


def restore_backup(session: Session, backup_file: str | Path) -> dict[str, Any]:
    backup_path = resolve_backup_path(backup_file)
    payload = load_backup(backup_path)
    data = payload["data"]

    try:
        business_ids: dict[int, int] = {}
        for record in data["businesses"]:
            old_id = _record_id(record, "businesses")
            restored = _upsert(
                session,
                Business,
                select(Business).where(Business.company_name == record["company_name"]),
                record,
            )
            business_ids[old_id] = _required_id(restored)

        service_ids: dict[int, int] = {}
        for record in data["services"]:
            old_id = _record_id(record, "services")
            restored = _upsert(
                session,
                Service,
                select(Service).where(Service.service_slug == record["service_slug"]),
                {**record, "business_id": _mapped_id(business_ids, record["business_id"], "services.business_id")},
            )
            service_ids[old_id] = _required_id(restored)

        county_ids: dict[int, int] = {}
        for record in data["counties"]:
            old_id = _record_id(record, "counties")
            restored = _upsert(
                session,
                County,
                select(County).where(
                    County.state == record["state"],
                    County.county_name == record["county_name"],
                ),
                record,
            )
            county_ids[old_id] = _required_id(restored)

        city_ids: dict[int, int] = {}
        for record in data["cities"]:
            old_id = _record_id(record, "cities")
            restored = _upsert(
                session,
                City,
                select(City).where(City.city_slug == record["city_slug"]),
                {**record, "county_id": _mapped_id(county_ids, record["county_id"], "cities.county_id")},
            )
            city_ids[old_id] = _required_id(restored)

        generated_page_ids: dict[int, int] = {}
        for record in data["generated_pages"]:
            old_id = _record_id(record, "generated_pages")
            restored_record = {
                **record,
                "business_id": _mapped_id(business_ids, record["business_id"], "generated_pages.business_id"),
                "service_id": _mapped_id(service_ids, record["service_id"], "generated_pages.service_id"),
                "city_id": _mapped_optional_id(city_ids, record.get("city_id"), "generated_pages.city_id"),
                "county_id": _mapped_optional_id(county_ids, record.get("county_id"), "generated_pages.county_id"),
            }
            restored = _upsert(
                session,
                GeneratedPage,
                select(GeneratedPage).where(GeneratedPage.page_slug == record["page_slug"]),
                restored_record,
            )
            generated_page_ids[old_id] = _required_id(restored)

        for record in data["approval_audits"]:
            page_id = _mapped_id(
                generated_page_ids,
                record["generated_page_id"],
                "approval_audits.generated_page_id",
            )
            approved_at = _datetime_value(record["approved_at"], "approval_audits.approved_at")
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "approved_at": approved_at,
                "qa_checked_at": _datetime_value(
                    record["qa_checked_at"],
                    "approval_audits.qa_checked_at",
                ),
            }
            _upsert(
                session,
                ApprovalAudit,
                select(ApprovalAudit).where(
                    ApprovalAudit.generated_page_id == page_id,
                    ApprovalAudit.approved_at == approved_at,
                    ApprovalAudit.draft_hash_at_approval == record["draft_hash_at_approval"],
                ),
                restored_record,
            )

        for record in data["page_revisions"]:
            page_id = _mapped_id(
                generated_page_ids,
                record["generated_page_id"],
                "page_revisions.generated_page_id",
            )
            created_at = _datetime_value(record["created_at"], "page_revisions.created_at")
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "created_at": created_at,
            }
            _upsert(
                session,
                GeneratedPageRevision,
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id,
                    GeneratedPageRevision.created_at == created_at,
                    GeneratedPageRevision.draft_hash_after == record["draft_hash_after"],
                ),
                restored_record,
            )

        wordpress_draft_audit_ids: dict[int, int] = {}
        for record in data["wordpress_draft_audits"]:
            old_audit_id = _record_id(record, "wordpress_draft_audits")
            page_id = _mapped_id(
                generated_page_ids,
                record["generated_page_id"],
                "wordpress_draft_audits.generated_page_id",
            )
            attempted_at = _datetime_value(
                record["attempted_at"],
                "wordpress_draft_audits.attempted_at",
            )
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "attempted_at": attempted_at,
                "qa_checked_at": (
                    _datetime_value(
                        record["qa_checked_at"],
                        "wordpress_draft_audits.qa_checked_at",
                    )
                    if record.get("qa_checked_at")
                    else None
                ),
            }
            restored_audit = _upsert(
                session,
                WordPressDraftAudit,
                select(WordPressDraftAudit).where(
                    WordPressDraftAudit.generated_page_id == page_id,
                    WordPressDraftAudit.attempted_at == attempted_at,
                    WordPressDraftAudit.payload_hash == record["payload_hash"],
                ),
                restored_record,
            )
            wordpress_draft_audit_ids[old_audit_id] = _required_id(restored_audit)

        for record in data["wordpress_publish_audits"]:
            page_id = _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_publish_audits.generated_page_id")
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_publish_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "attempted_at": attempted_at,
                "completed_at": (
                    _datetime_value(record["completed_at"], "wordpress_publish_audits.completed_at")
                    if record.get("completed_at") else None
                ),
                "latest_update_audit_id": _mapped_optional_id(
                    wordpress_draft_audit_ids,
                    record.get("latest_update_audit_id"),
                    "wordpress_publish_audits.latest_update_audit_id",
                ),
            }
            _upsert(
                session,
                WordPressPublishAudit,
                select(WordPressPublishAudit).where(
                    WordPressPublishAudit.generated_page_id == page_id,
                    WordPressPublishAudit.attempted_at == attempted_at,
                    WordPressPublishAudit.publish_payload_hash == record["publish_payload_hash"],
                ),
                restored_record,
            )

        for record in data["wordpress_quality_reviews"]:
            page_id = _mapped_id(
                generated_page_ids,
                record["generated_page_id"],
                "wordpress_quality_reviews.generated_page_id",
            )
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "reviewed_at": (
                    _datetime_value(
                        record["reviewed_at"],
                        "wordpress_quality_reviews.reviewed_at",
                    )
                    if record.get("reviewed_at")
                    else None
                ),
                "created_at": _datetime_value(
                    record["created_at"],
                    "wordpress_quality_reviews.created_at",
                ),
                "updated_at": _datetime_value(
                    record["updated_at"],
                    "wordpress_quality_reviews.updated_at",
                ),
            }
            _upsert(
                session,
                WordPressQualityReview,
                select(WordPressQualityReview).where(
                    WordPressQualityReview.generated_page_id == page_id,
                ),
                restored_record,
            )

        image_metadata_ids: dict[int, int] = {}
        for record in data["image_metadata"]:
            old_id = _record_id(record, "image_metadata")
            business_id = _mapped_id(business_ids, record["business_id"], "image_metadata.business_id")
            restored_record = {
                **record,
                "business_id": business_id,
                "service_id": _mapped_optional_id(service_ids, record.get("service_id"), "image_metadata.service_id"),
                "city_id": _mapped_optional_id(city_ids, record.get("city_id"), "image_metadata.city_id"),
                "county_id": _mapped_optional_id(county_ids, record.get("county_id"), "image_metadata.county_id"),
            }
            restored = _upsert(
                session,
                ImageMetadata,
                select(ImageMetadata).where(
                    ImageMetadata.business_id == business_id,
                    ImageMetadata.file_name == record["file_name"],
                ),
                restored_record,
            )
            image_metadata_ids[old_id] = _required_id(restored)

        page_image_assignment_ids: dict[int, int] = {}
        for record in data["page_image_assignments"]:
            old_assignment_id = _record_id(record, "page_image_assignments")
            page_id = _mapped_id(
                generated_page_ids,
                record["generated_page_id"],
                "page_image_assignments.generated_page_id",
            )
            restored_record = {
                **record,
                "generated_page_id": page_id,
                "image_metadata_id": _mapped_id(
                    image_metadata_ids,
                    record["image_metadata_id"],
                    "page_image_assignments.image_metadata_id",
                ),
            }
            restored_assignment = _upsert(
                session,
                PageImageAssignment,
                select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page_id,
                    PageImageAssignment.image_metadata_id == restored_record["image_metadata_id"],
                    PageImageAssignment.image_role == record["image_role"],
                ),
                restored_record,
            )
            page_image_assignment_ids[old_assignment_id] = _required_id(restored_assignment)

        for record in data["wordpress_media_sync_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_media_sync_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_media_sync_audits.generated_page_id"),
                "image_metadata_id": _mapped_id(image_metadata_ids, record["image_metadata_id"], "wordpress_media_sync_audits.image_metadata_id"),
                "page_image_assignment_id": _mapped_id(page_image_assignment_ids, record["page_image_assignment_id"], "wordpress_media_sync_audits.page_image_assignment_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_media_sync_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(
                session, WordPressMediaSyncAudit,
                select(WordPressMediaSyncAudit).where(
                    WordPressMediaSyncAudit.generated_page_id == restored_record["generated_page_id"],
                    WordPressMediaSyncAudit.attempted_at == attempted_at,
                    WordPressMediaSyncAudit.source_checksum == record["source_checksum"],
                ), restored_record,
            )

        for record in data["settings"]:
            if is_sensitive_setting_key(record["setting_key"]):
                continue
            _upsert(
                session,
                Setting,
                select(Setting).where(Setting.setting_key == record["setting_key"]),
                record,
            )

        for record in data["knowledge_blocks"]:
            restored_record = {
                **record,
                "business_id": _mapped_id(business_ids, record["business_id"], "knowledge_blocks.business_id"),
                "service_id": _mapped_id(service_ids, record["service_id"], "knowledge_blocks.service_id"),
            }
            _upsert(
                session,
                KnowledgeBlock,
                select(KnowledgeBlock).where(KnowledgeBlock.slug == record["slug"]),
                restored_record,
            )

        session.commit()
    except Exception as exc:
        session.rollback()
        if isinstance(exc, BackupValidationError):
            raise
        raise BackupValidationError(f"Restore failed and was rolled back: {exc}") from exc

    return {
        "file_name": backup_path.name,
        "status": "restored",
        "records_processed": sum(payload["metadata"]["table_counts"].values()),
        "table_counts": payload["metadata"]["table_counts"],
    }


def is_sensitive_setting_key(setting_key: str) -> bool:
    normalized = setting_key.strip().lower().replace("-", "_").replace(" ", "_")
    return any(marker in normalized for marker in SENSITIVE_SETTING_MARKERS)


def load_backup(backup_path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(backup_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupValidationError(f"Backup file not found: {backup_path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupValidationError(f"Backup file is not valid JSON: {backup_path}") from exc

    if not isinstance(payload, dict):
        raise BackupValidationError("Backup root must be a JSON object.")
    metadata = payload.get("metadata")
    data = payload.get("data")
    if not isinstance(metadata, dict) or not isinstance(data, dict):
        raise BackupValidationError("Backup must contain metadata and data objects.")
    if metadata.get("app") != APP_NAME:
        raise BackupValidationError("Backup app label does not match Project Atlas.")
    backup_version = metadata.get("version")
    if backup_version not in SUPPORTED_BACKUP_VERSIONS:
        supported = ", ".join(sorted(SUPPORTED_BACKUP_VERSIONS))
        raise BackupValidationError(f"Unsupported backup version; expected one of: {supported}.")
    if not isinstance(metadata.get("created_at"), str):
        raise BackupValidationError("Backup created_at timestamp is missing.")
    try:
        datetime.fromisoformat(metadata["created_at"])
    except ValueError as exc:
        raise BackupValidationError("Backup created_at timestamp is invalid.") from exc

    counts = metadata.get("table_counts")
    if not isinstance(counts, dict):
        raise BackupValidationError("Backup table_counts must be an object.")
    if backup_version in {"0.4", "0.5"} and "page_image_assignments" not in data:
        data["page_image_assignments"] = []
        counts["page_image_assignments"] = 0
    if backup_version != "0.12" and "approval_audits" not in data:
        data["approval_audits"] = []
        counts["approval_audits"] = 0
    if backup_version != "0.13" and "page_revisions" not in data:
        data["page_revisions"] = []
        counts["page_revisions"] = 0
    if backup_version != "0.17" and "wordpress_draft_audits" not in data:
        data["wordpress_draft_audits"] = []
        counts["wordpress_draft_audits"] = 0
    if backup_version != "0.27" and "wordpress_quality_reviews" not in data:
        data["wordpress_quality_reviews"] = []
        counts["wordpress_quality_reviews"] = 0
    if backup_version != "0.28" and "wordpress_publish_audits" not in data:
        data["wordpress_publish_audits"] = []
        counts["wordpress_publish_audits"] = 0
    if backup_version != "0.29" and "wordpress_media_sync_audits" not in data:
        data["wordpress_media_sync_audits"] = []
        counts["wordpress_media_sync_audits"] = 0

    for group in BACKUP_MODELS:
        records = data.get(group)
        if not isinstance(records, list):
            raise BackupValidationError(f"Backup data group '{group}' must be a list.")
        if counts.get(group) != len(records):
            raise BackupValidationError(f"Backup count mismatch for '{group}'.")
        if not all(isinstance(record, dict) for record in records):
            raise BackupValidationError(f"Backup data group '{group}' contains an invalid record.")

    _validate_unique_records(data)
    _validate_backup_references(data)
    return payload


def resolve_backup_path(backup_file: str | Path) -> Path:
    requested = Path(backup_file)
    candidates = [requested] if requested.is_absolute() else [Path.cwd() / requested, BACKEND_ROOT / requested]
    if not requested.is_absolute() and requested.parts and requested.parts[0].lower() == "backend":
        candidates.append(BACKEND_ROOT.joinpath(*requested.parts[1:]))
    candidates.append(BACKUP_DIR / requested.name)

    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise BackupValidationError(f"Backup file not found: {backup_file}")


def resolve_backup_download(file_name: str) -> Path:
    if (
        Path(file_name).name != file_name
        or not file_name.startswith("atlas-backup-")
        or not file_name.endswith(".json")
    ):
        raise BackupValidationError("Invalid Atlas backup filename.")
    backup_path = (BACKUP_DIR / file_name).resolve()
    if backup_path.parent != BACKUP_DIR.resolve() or not backup_path.is_file():
        raise BackupValidationError(f"Backup file not found: {file_name}")
    return backup_path


def _available_backup_path(destination: Path, timestamp: datetime) -> Path:
    candidate_time = timestamp
    while True:
        candidate = destination / f"atlas-backup-{candidate_time.strftime('%Y-%m-%d-%H%M%S')}.json"
        if not candidate.exists():
            return candidate
        candidate_time += timedelta(seconds=1)


def _upsert(
    session: Session,
    model: type[SQLModel],
    statement: Any,
    payload: dict[str, Any],
) -> SQLModel:
    normalized = model.model_validate(payload)
    values = normalized.model_dump(exclude={"id"})
    existing = session.exec(statement).first()
    if existing:
        for key, value in values.items():
            setattr(existing, key, value)
        record = existing
    else:
        record = model(**values)
    session.add(record)
    session.flush()
    return record


def _record_id(record: dict[str, Any], group: str) -> int:
    record_id = record.get("id")
    if not isinstance(record_id, int):
        raise BackupValidationError(f"Every '{group}' record must have an integer id.")
    return record_id


def _required_id(record: SQLModel) -> int:
    record_id = getattr(record, "id", None)
    if not isinstance(record_id, int):
        raise BackupValidationError("Restored record did not receive a database id.")
    return record_id


def _mapped_id(mapping: dict[int, int], old_id: Any, field: str) -> int:
    if not isinstance(old_id, int) or old_id not in mapping:
        raise BackupValidationError(f"Backup contains an unresolved reference in {field}.")
    return mapping[old_id]


def _mapped_optional_id(mapping: dict[int, int], old_id: Any, field: str) -> int | None:
    if old_id is None:
        return None
    return _mapped_id(mapping, old_id, field)


def _datetime_value(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise BackupValidationError(f"Backup contains an invalid timestamp in {field}.") from exc
    raise BackupValidationError(f"Backup contains an invalid timestamp in {field}.")


def _validate_unique_records(data: dict[str, list[dict[str, Any]]]) -> None:
    key_fields: dict[str, tuple[str, ...]] = {
        "businesses": ("company_name",),
        "services": ("service_slug",),
        "counties": ("state", "county_name"),
        "cities": ("city_slug",),
        "generated_pages": ("page_slug",),
        "approval_audits": ("generated_page_id", "approved_at", "draft_hash_at_approval"),
        "page_revisions": ("generated_page_id", "created_at", "draft_hash_after"),
        "wordpress_draft_audits": ("generated_page_id", "attempted_at", "payload_hash"),
        "wordpress_publish_audits": ("generated_page_id", "attempted_at", "publish_payload_hash"),
        "wordpress_media_sync_audits": ("generated_page_id", "attempted_at", "source_checksum"),
        "wordpress_quality_reviews": ("generated_page_id",),
        "image_metadata": ("business_id", "file_name"),
        "page_image_assignments": ("generated_page_id", "image_metadata_id", "image_role"),
        "settings": ("setting_key",),
        "knowledge_blocks": ("slug",),
    }
    for group, fields in key_fields.items():
        seen: set[tuple[Any, ...]] = set()
        ids: set[int] = set()
        for record in data[group]:
            record_id = _record_id(record, group)
            key = tuple(record.get(field) for field in fields)
            if any(value is None or value == "" for value in key):
                raise BackupValidationError(f"Backup record in '{group}' is missing a stable key.")
            if record_id in ids or key in seen:
                raise BackupValidationError(f"Backup contains duplicate records in '{group}'.")
            ids.add(record_id)
            seen.add(key)


def _validate_backup_references(data: dict[str, list[dict[str, Any]]]) -> None:
    ids = {group: {record["id"] for record in records} for group, records in data.items()}
    references = {
        "services": (("business_id", "businesses", False),),
        "cities": (("county_id", "counties", False),),
        "generated_pages": (
            ("business_id", "businesses", False),
            ("service_id", "services", False),
            ("city_id", "cities", True),
            ("county_id", "counties", True),
        ),
        "image_metadata": (
            ("business_id", "businesses", False),
            ("service_id", "services", True),
            ("city_id", "cities", True),
            ("county_id", "counties", True),
        ),
        "knowledge_blocks": (
            ("business_id", "businesses", False),
            ("service_id", "services", False),
        ),
        "page_image_assignments": (
            ("generated_page_id", "generated_pages", False),
            ("image_metadata_id", "image_metadata", False),
        ),
        "approval_audits": (
            ("generated_page_id", "generated_pages", False),
        ),
        "page_revisions": (
            ("generated_page_id", "generated_pages", False),
        ),
        "wordpress_draft_audits": (
            ("generated_page_id", "generated_pages", False),
        ),
        "wordpress_publish_audits": (
            ("generated_page_id", "generated_pages", False),
            ("latest_update_audit_id", "wordpress_draft_audits", True),
        ),
        "wordpress_quality_reviews": (
            ("generated_page_id", "generated_pages", False),
        ),
        "wordpress_media_sync_audits": (
            ("generated_page_id", "generated_pages", False),
            ("image_metadata_id", "image_metadata", False),
            ("page_image_assignment_id", "page_image_assignments", False),
        ),
    }
    for group, group_references in references.items():
        for record in data[group]:
            for field, target_group, optional in group_references:
                value = record.get(field)
                if optional and value is None:
                    continue
                if value not in ids[target_group]:
                    raise BackupValidationError(f"Backup contains an unresolved reference in {group}.{field}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or restore Project Atlas JSON backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("export", help="Export all Atlas data to the backups folder.")
    restore_parser = subparsers.add_parser("restore", help="Restore a JSON backup with non-destructive upserts.")
    restore_parser.add_argument("backup_file", help="Path or file name of the backup to restore.")
    args = parser.parse_args()

    try:
        create_db_and_tables()
        with Session(engine) as session:
            if args.command == "export":
                result = export_backup(session)
            else:
                result = restore_backup(session, args.backup_file)
    except (BackupValidationError, OSError) as exc:
        parser.exit(1, f"Backup error: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
