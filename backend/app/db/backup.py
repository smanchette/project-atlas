import argparse
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import inspect as sa_inspect, text
from sqlmodel import Session, SQLModel, select

from app.core.config import get_settings
from app.db.session import create_db_and_tables, engine
from app.services.media_display_presets import (
    DisplayPresetError,
    effective_assignment_display_preset,
)
from app.services.page_qa import historical_qa_payload_hash, qa_result_record_hash
from app.models import (
    ApprovalAudit,
    Brand,
    BrandAsset,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    FormDeliveryAttempt,
    FormDeliveryConfigurationAudit,
    FormDeliveryOutbox,
    FormSubmissionEnvelope,
    WebsiteDraftGenerationItem,
    WebsiteDraftGenerationRun,
    GeneratedPage,
    GeneratedPageQAResult,
    GeneratedPageRevision,
    ImageMetadata,
    InternalLinkIntent,
    KnowledgeBlock,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlannedPageMediaRequirement,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    SiteConnectionPlanningRecord,
    Service,
    SemanticComponentDefinition,
    ScopedMediaAuthorization,
    Setting,
    SitePlan,
    SupportingPageAuthorization,
    Theme,
    ThemeConfigurationAudit,
    ThemeFamily,
    ThemeFamilyVersion,
    Website,
    WebsiteFormDeliveryModeRevision,
    WebsiteFormRecipientRevision,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteCoveragePlanningRecord,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteMediaPlanningRecord,
    WebsiteThemeSelection,
    WebsiteThemeComponentConfiguration,
    WebsiteThemeConfiguration,
    WebsiteServiceCityCoverageDecision,
    WebsiteServiceCountyCoverageDecision,
    WebsiteServiceCoverageDecision,
    WordPressDraftAudit,
    WordPressHeadingCorrectionAudit,
    WordPressDeploymentAudit,
    WordPressDeploymentNonce,
    WordPressDeploymentTransition,
    WordPressActivationAudit,
    WordPressPluginUpgradeAudit,
    WordPressBootstrapCleanupAudit,
    WordPressBootstrapEstablishmentAudit,
    WordPressMetadataLifecycleAudit,
    WordPressCacheAwareRenderingAudit,
    WordPressMediaSyncAudit,
    WordPressMetadataState,
    WordPressMetadataSyncAudit,
    WordPressPublishAudit,
    WordPressQualityReview,
)
from app.schemas.scoped_media_authorizations import (
    SCOPED_MEDIA_AUTHORIZATION_TERMS,
    normalize_scoped_media_authorization_terms,
    normalize_scoped_media_required_terms,
    scoped_media_approval_fingerprint,
    scoped_media_authorization_fingerprint,
    validate_scoped_media_authorization_policy_terms,
)

APP_NAME = "Project Atlas"
BACKUP_VERSION = "0.58"
BRAND_ASSET_KEY_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
BRAND_ASSET_MIME_EXTENSIONS = {
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
}
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
    "0.30",
    "0.31",
    "0.32",
    "0.33",
    "0.34",
    "0.35",
    "0.36",
    "0.37",
    "0.38",
    "0.39",
    "0.40",
    "0.41",
    "0.42",
    "0.43",
    "0.44",
    "0.45",
    "0.46",
    "0.47",
    "0.48",
    "0.49",
    "0.50",
    "0.51",
    "0.52",
    "0.53",
    "0.54",
    "0.55",
    "0.56",
    "0.57",
    "0.58",
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
_RESTORE_PRESERVE_SOURCE_IDS = "atlas_restore_preserve_source_ids"
_RESTORE_EXPLICIT_ID_MODELS = "atlas_restore_explicit_id_models"

BACKUP_MODELS: dict[str, type[SQLModel]] = {
    "businesses": Business,
    "brands": Brand,
    "websites": Website,
    "website_identities": WebsiteIdentity,
    "brand_assets": BrandAsset,
    "website_identity_asset_assignments": WebsiteIdentityAssetAssignment,
    "themes": Theme,
    "website_theme_selections": WebsiteThemeSelection,
    "services": Service,
    "counties": County,
    "cities": City,
    "generated_pages": GeneratedPage,
    "generated_page_qa_results": GeneratedPageQAResult,
    "site_plans": SitePlan,
    "planned_pages": PlannedPage,
    "planning_records": PlanningRecord,
    "website_media_planning_records": WebsiteMediaPlanningRecord,
    "planned_page_media_requirements": PlannedPageMediaRequirement,
    "site_connection_planning_records": SiteConnectionPlanningRecord,
    "website_coverage_planning_records": WebsiteCoveragePlanningRecord,
    "website_service_coverage_decisions": WebsiteServiceCoverageDecision,
    "website_county_coverage_decisions": WebsiteCountyCoverageDecision,
    "website_city_coverage_decisions": WebsiteCityCoverageDecision,
    "website_service_city_coverage_decisions": WebsiteServiceCityCoverageDecision,
    "website_service_county_coverage_decisions": WebsiteServiceCountyCoverageDecision,
    "supporting_page_authorizations": SupportingPageAuthorization,
    "pre_draft_distinctness_briefs": PreDraftDistinctnessBrief,
    "drafting_eligibility_assessments": DraftingEligibilityAssessment,
    "drafting_eligibility_dispositions": DraftingEligibilityDisposition,
    "website_draft_generation_runs": WebsiteDraftGenerationRun,
    "website_draft_generation_items": WebsiteDraftGenerationItem,
    "navigation_sets": NavigationSet,
    "navigation_items": NavigationItem,
    "internal_link_intents": InternalLinkIntent,
    "semantic_component_definitions": SemanticComponentDefinition,
    "page_compositions": PageComposition,
    "theme_families": ThemeFamily,
    "theme_family_versions": ThemeFamilyVersion,
    "website_theme_configurations": WebsiteThemeConfiguration,
    "website_theme_component_configurations": WebsiteThemeComponentConfiguration,
    "theme_configuration_audits": ThemeConfigurationAudit,
    "website_form_delivery_mode_revisions": WebsiteFormDeliveryModeRevision,
    "website_form_recipient_revisions": WebsiteFormRecipientRevision,
    "form_submission_envelopes": FormSubmissionEnvelope,
    "form_delivery_outbox_records": FormDeliveryOutbox,
    "form_delivery_attempts": FormDeliveryAttempt,
    "form_delivery_configuration_audits": FormDeliveryConfigurationAudit,
    "approval_audits": ApprovalAudit,
    "page_revisions": GeneratedPageRevision,
    "wordpress_draft_audits": WordPressDraftAudit,
    "wordpress_heading_correction_audits": WordPressHeadingCorrectionAudit,
    "wordpress_deployment_audits": WordPressDeploymentAudit,
    "wordpress_deployment_nonces": WordPressDeploymentNonce,
    "wordpress_deployment_transitions": WordPressDeploymentTransition,
    "wordpress_activation_audits": WordPressActivationAudit,
    "wordpress_plugin_upgrade_audits": WordPressPluginUpgradeAudit,
    "wordpress_bootstrap_cleanup_audits": WordPressBootstrapCleanupAudit,
    "wordpress_bootstrap_establishment_audits": WordPressBootstrapEstablishmentAudit,
    "wordpress_metadata_lifecycle_audits": WordPressMetadataLifecycleAudit,
    "wordpress_cache_aware_rendering_audits": WordPressCacheAwareRenderingAudit,
    "wordpress_publish_audits": WordPressPublishAudit,
    "wordpress_media_sync_audits": WordPressMediaSyncAudit,
    "wordpress_metadata_states": WordPressMetadataState,
    "wordpress_metadata_sync_audits": WordPressMetadataSyncAudit,
    "wordpress_quality_reviews": WordPressQualityReview,
    "image_metadata": ImageMetadata,
    "page_image_assignments": PageImageAssignment,
    "scoped_media_authorizations": ScopedMediaAuthorization,
    "settings": Setting,
    "knowledge_blocks": KnowledgeBlock,
}

FORM_DELIVERY_BACKUP_GROUPS = (
    "website_form_delivery_mode_revisions",
    "website_form_recipient_revisions",
    "form_submission_envelopes",
    "form_delivery_outbox_records",
    "form_delivery_attempts",
    "form_delivery_configuration_audits",
)
_FORM_DELIVERY_TEST_PAYLOAD_REFERENCE_PATTERN = re.compile(
    r"^memory://form-payload/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_FORM_DELIVERY_STABLE_METADATA_KEY_PATTERN = re.compile(
    r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$"
)
_FORM_DELIVERY_OPAQUE_SOURCE_REFERENCE_PATTERN = re.compile(
    r"^source-ref://[a-z0-9][a-z0-9/_-]{2,239}$"
)
_FORM_DELIVERY_TEST_KEY_REFERENCE = "secret-ref://synthetic/form-payload-key"
_FORM_DELIVERY_COLLECTOR_MODES = {
    "atlas_email",
    "atlasops360_native",
    "external_adapter",
}

_UTC_NAVIGATION_DECISION_GROUPS = (
    "navigation_sets",
    "navigation_items",
    "internal_link_intents",
)

# Exact Backup-model projection of revision 0046's TIMESTAMPTZ_COLUMNS.  These
# fields represented UTC instants before 0046 and differ only in whether the
# PostgreSQL driver returns a naive value or an explicit UTC offset afterward.
_CONVERGED_UTC_TIMESTAMP_FIELDS = {
    "site_connection_planning_records": (
        "created_at",
        "updated_at",
        "generated_at",
    ),
    "navigation_sets": ("created_at", "updated_at"),
    "navigation_items": ("created_at", "updated_at"),
    "internal_link_intents": ("created_at", "updated_at"),
    "website_coverage_planning_records": (
        "created_at",
        "updated_at",
        "generated_at",
    ),
    "website_service_coverage_decisions": (
        "created_at",
        "updated_at",
        "decided_at",
    ),
    "website_county_coverage_decisions": (
        "created_at",
        "updated_at",
        "decided_at",
    ),
    "website_city_coverage_decisions": (
        "created_at",
        "updated_at",
        "decided_at",
    ),
    "website_service_city_coverage_decisions": (
        "created_at",
        "updated_at",
        "decided_at",
    ),
}
_CONVERGED_UTC_MODEL_FIELDS = {
    BACKUP_MODELS[group]: fields
    for group, fields in _CONVERGED_UTC_TIMESTAMP_FIELDS.items()
}

_FORM_DELIVERY_UTC_TIMESTAMP_FIELDS = {
    "website_form_delivery_mode_revisions": (
        "created_at",
        "updated_at",
        "approved_at",
        "activated_at",
    ),
    "website_form_recipient_revisions": (
        "created_at",
        "updated_at",
        "verified_at",
    ),
    "form_submission_envelopes": ("received_at", "expires_at"),
    "form_delivery_outbox_records": (
        "created_at",
        "updated_at",
        "next_attempt_at",
        "delivered_at",
        "failed_at",
        "expired_at",
    ),
    "form_delivery_attempts": ("started_at", "completed_at", "next_retry_at"),
    "form_delivery_configuration_audits": ("created_at",),
}
_FORM_DELIVERY_UTC_MODEL_FIELDS = {
    BACKUP_MODELS[group]: fields
    for group, fields in _FORM_DELIVERY_UTC_TIMESTAMP_FIELDS.items()
}


class BackupValidationError(ValueError):
    pass


LEGACY_QA_PROJECTION_FIELDS = {
    "page_id",
    "readiness_status",
    "checked_at",
    "passed_count",
    "warning_count",
    "failed_count",
    "checks",
}
CANDIDATE_QA_PROJECTION_FIELDS = {
    "qa_result_id",
    "page_id",
    "website_id",
    "site_plan_id",
    "planned_page_id",
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
    "checked_at",
    "passed_count",
    "warning_count",
    "failed_count",
    "checks",
    "result_hash",
    "lifecycle_status",
    "currentness_status",
    "currentness_reasons",
}


def export_backup(
    session: Session,
    *,
    backup_dir: Path | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    form_delivery_tables_available = _form_delivery_export_tables_available(session)
    destination = backup_dir or BACKUP_DIR
    destination.mkdir(parents=True, exist_ok=True)
    timestamp = (created_at or datetime.now(UTC)).astimezone(UTC)

    data = {}
    for group, model in BACKUP_MODELS.items():
        if group in FORM_DELIVERY_BACKUP_GROUPS and not form_delivery_tables_available:
            data[group] = []
            continue
        records = session.exec(select(model).order_by(model.id)).all()
        if group == "settings":
            records = [
                record
                for record in records
                if not is_sensitive_setting_key(record.setting_key)
            ]
        data[group] = [record.model_dump(mode="json") for record in records]
    _canonicalize_navigation_decision_timestamps(data)
    _canonicalize_converged_utc_timestamps(data)
    _canonicalize_form_delivery_utc_timestamps(data)
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
    serialized = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
    descriptor, validation_name = tempfile.mkstemp(
        dir=destination,
        prefix=".atlas-backup-",
        suffix=".validating",
        text=True,
    )
    validation_path = Path(validation_name)
    backup_path: Path | None = None
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        load_backup(validation_path)
        backup_path = _reserve_backup_path(destination, timestamp)
        validation_path.replace(backup_path)
    except Exception:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)
        raise
    finally:
        validation_path.unlink(missing_ok=True)

    if backup_path is None:  # pragma: no cover - defensive type narrowing
        raise BackupValidationError("Backup publication did not reserve a destination.")

    return {
        "file_name": backup_path.name,
        "path": str(backup_path),
        "created_at": timestamp.isoformat(),
        "table_counts": table_counts,
        "status": "created",
    }


def _form_delivery_export_tables_available(session: Session) -> bool:
    """Accept only the complete 0047 table set or the complete pre-0047 absence."""

    expected_tables = {
        BACKUP_MODELS[group].__table__.key for group in FORM_DELIVERY_BACKUP_GROUPS
    }
    available_tables = set(sa_inspect(session.connection()).get_table_names())
    present_tables = expected_tables & available_tables
    if present_tables and present_tables != expected_tables:
        missing = ", ".join(sorted(expected_tables - present_tables))
        present = ", ".join(sorted(present_tables))
        raise BackupValidationError(
            "Backup refused a partial universal form-delivery schema; "
            f"present tables: {present}; missing tables: {missing}."
        )
    return present_tables == expected_tables


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
        preserve_source_ids = _restore_managed_tables_are_empty(
            session, data
        ) or _restore_managed_tables_match_backup(session, data)
        preserve_current_composition_identity = bool(
            preserve_source_ids
            and payload["metadata"]["version"] in {"0.57", "0.58"}
        )
    except Exception as exc:
        raise BackupValidationError(
            "Restore could not prove whether every managed target table is empty."
        ) from exc
    session.info[_RESTORE_PRESERVE_SOURCE_IDS] = preserve_source_ids
    session.info[_RESTORE_EXPLICIT_ID_MODELS] = set()

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

        brand_ids: dict[int, int] = {}
        for record in data.get("brands", []):
            old_id = _record_id(record, "brands")
            business_id = _mapped_id(business_ids, record["business_id"], "brands.business_id")
            restored = _upsert(
                session,
                Brand,
                select(Brand).where(
                    Brand.business_id == business_id,
                    Brand.brand_name == record["brand_name"],
                ),
                {**record, "business_id": business_id},
            )
            brand_ids[old_id] = _required_id(restored)

        website_ids: dict[int, int] = {}
        for record in data.get("websites", []):
            old_id = _record_id(record, "websites")
            business_id = _mapped_id(business_ids, record["business_id"], "websites.business_id")
            restored = _upsert(
                session,
                Website,
                select(Website).where(
                    Website.business_id == business_id,
                    Website.domain == record["domain"],
                ),
                {
                    **record,
                    "business_id": business_id,
                    "brand_id": _mapped_optional_id(brand_ids, record.get("brand_id"), "websites.brand_id"),
                },
            )
            website_ids[old_id] = _required_id(restored)

        website_identity_ids: dict[int, int] = {}
        for record in data.get("website_identities", []):
            old_id = _record_id(record, "website_identities")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_identities.website_id",
            )
            restored = _upsert(
                session,
                WebsiteIdentity,
                select(WebsiteIdentity).where(WebsiteIdentity.website_id == website_id),
                {**record, "website_id": website_id},
            )
            website_identity_ids[old_id] = _required_id(restored)

        brand_asset_ids: dict[int, int] = {}
        pending_asset_replacements: list[tuple[dict[str, Any], BrandAsset]] = []
        for record in data.get("brand_assets", []):
            old_id = _record_id(record, "brand_assets")
            brand_id = _mapped_id(brand_ids, record["brand_id"], "brand_assets.brand_id")
            restored = _upsert(
                session,
                BrandAsset,
                select(BrandAsset).where(
                    BrandAsset.brand_id == brand_id,
                    BrandAsset.asset_key == record["asset_key"],
                    BrandAsset.version == record["version"],
                ),
                {
                    **record,
                    "business_id": _mapped_id(business_ids, record["business_id"], "brand_assets.business_id"),
                    "brand_id": brand_id,
                    "replaces_brand_asset_id": None,
                },
            )
            brand_asset_ids[old_id] = _required_id(restored)
            pending_asset_replacements.append((record, restored))
        for record, restored in pending_asset_replacements:
            restored.replaces_brand_asset_id = _mapped_optional_id(
                brand_asset_ids,
                record.get("replaces_brand_asset_id"),
                "brand_assets.replaces_brand_asset_id",
            )
            session.add(restored)
        session.flush()

        for record in data.get("website_identity_asset_assignments", []):
            identity_id = _mapped_id(
                website_identity_ids,
                record["website_identity_id"],
                "website_identity_asset_assignments.website_identity_id",
            )
            slot = record["slot"]
            version = record["version"]
            _upsert(
                session,
                WebsiteIdentityAssetAssignment,
                select(WebsiteIdentityAssetAssignment).where(
                    WebsiteIdentityAssetAssignment.website_identity_id == identity_id,
                    WebsiteIdentityAssetAssignment.slot == slot,
                    WebsiteIdentityAssetAssignment.version == version,
                ),
                {
                    **record,
                    "website_identity_id": identity_id,
                    "website_id": _mapped_id(website_ids, record["website_id"], "website_identity_asset_assignments.website_id"),
                    "brand_id": _mapped_id(brand_ids, record["brand_id"], "website_identity_asset_assignments.brand_id"),
                    "brand_asset_id": _mapped_id(brand_asset_ids, record["brand_asset_id"], "website_identity_asset_assignments.brand_asset_id"),
                },
            )

        theme_ids: dict[int, int] = {}
        pending_theme_replacements: list[tuple[dict[str, Any], Theme]] = []
        for record in data.get("themes", []):
            old_id = _record_id(record, "themes")
            website_id = _mapped_id(
                website_ids, record["website_id"], "themes.website_id"
            )
            restored = _upsert(
                session,
                Theme,
                select(Theme).where(
                    Theme.website_id == website_id,
                    Theme.theme_key == record["theme_key"],
                    Theme.version == record["version"],
                ),
                {
                    **record,
                    "website_id": website_id,
                    "business_id": _mapped_id(
                        business_ids, record["business_id"], "themes.business_id"
                    ),
                    "brand_id": _mapped_id(
                        brand_ids, record["brand_id"], "themes.brand_id"
                    ),
                    "replaces_theme_id": None,
                },
            )
            theme_ids[old_id] = _required_id(restored)
            pending_theme_replacements.append((record, restored))
        for record, restored in pending_theme_replacements:
            restored.replaces_theme_id = _mapped_optional_id(
                theme_ids,
                record.get("replaces_theme_id"),
                "themes.replaces_theme_id",
            )
            session.add(restored)
        session.flush()

        website_theme_selection_ids: dict[int, int] = {}
        for record in data.get("website_theme_selections", []):
            old_id = _record_id(record, "website_theme_selections")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_theme_selections.website_id",
            )
            restored = _upsert(
                session,
                WebsiteThemeSelection,
                select(WebsiteThemeSelection).where(
                    WebsiteThemeSelection.website_id == website_id,
                    WebsiteThemeSelection.version == record["version"],
                ),
                {
                    **record,
                    "website_id": website_id,
                    "theme_id": _mapped_id(
                        theme_ids,
                        record["theme_id"],
                        "website_theme_selections.theme_id",
                    ),
                },
            )
            website_theme_selection_ids[old_id] = _required_id(restored)

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
        pending_generated_page_qa_projections: list[
            tuple[dict[str, Any] | None, GeneratedPage]
        ] = []
        for record in data["generated_pages"]:
            old_id = _record_id(record, "generated_pages")
            restored_record = {
                **record,
                # Nested QA projections contain backup-local page identities.
                # Restore the enclosing page first, then bind the projection to
                # the remapped page id below.
                "qa_result": None,
                "business_id": _mapped_id(business_ids, record["business_id"], "generated_pages.business_id"),
                "service_id": _mapped_optional_id(
                    service_ids,
                    record.get("service_id"),
                    "generated_pages.service_id",
                ),
                "city_id": _mapped_optional_id(city_ids, record.get("city_id"), "generated_pages.city_id"),
                "county_id": _mapped_optional_id(county_ids, record.get("county_id"), "generated_pages.county_id"),
                "website_id": _mapped_optional_id(
                    website_ids,
                    record.get("website_id"),
                    "generated_pages.website_id",
                ),
            }
            restored = _upsert(
                session,
                GeneratedPage,
                select(GeneratedPage).where(
                    GeneratedPage.website_id == restored_record["website_id"],
                    GeneratedPage.page_slug == record["page_slug"],
                ),
                restored_record,
            )
            restored_page_id = _required_id(restored)
            generated_page_ids[old_id] = restored_page_id
            pending_generated_page_qa_projections.append(
                (record.get("qa_result"), restored)
            )

        site_plan_ids: dict[int, int] = {}
        for record in data.get("site_plans", []):
            old_id = _record_id(record, "site_plans")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "site_plans.website_id",
            )
            restored = _upsert(
                session,
                SitePlan,
                select(SitePlan).where(
                    SitePlan.website_id == website_id,
                    SitePlan.plan_key == record["plan_key"],
                ),
                {**record, "website_id": website_id},
            )
            site_plan_ids[old_id] = _required_id(restored)

        planned_page_ids: dict[int, int] = {}
        pending_planned_records: list[tuple[dict[str, Any], PlannedPage]] = []
        for record in data.get("planned_pages", []):
            old_id = _record_id(record, "planned_pages")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "planned_pages.website_id",
            )
            restored_record = {
                **record,
                "website_id": website_id,
                "site_plan_id": _mapped_id(
                    site_plan_ids,
                    record["site_plan_id"],
                    "planned_pages.site_plan_id",
                ),
                "service_id": _mapped_optional_id(
                    service_ids,
                    record.get("service_id"),
                    "planned_pages.service_id",
                ),
                "city_id": _mapped_optional_id(
                    city_ids,
                    record.get("city_id"),
                    "planned_pages.city_id",
                ),
                "county_id": _mapped_optional_id(
                    county_ids,
                    record.get("county_id"),
                    "planned_pages.county_id",
                ),
                "generated_page_id": _mapped_optional_id(
                    generated_page_ids,
                    record.get("generated_page_id"),
                    "planned_pages.generated_page_id",
                ),
                "parent_planned_page_id": None,
            }
            restored = _upsert(
                session,
                PlannedPage,
                select(PlannedPage).where(
                    PlannedPage.website_id == website_id,
                    PlannedPage.intended_slug == record["intended_slug"],
                ),
                restored_record,
            )
            planned_page_ids[old_id] = _required_id(restored)
            pending_planned_records.append((record, restored))
        for record, restored in pending_planned_records:
            restored.parent_planned_page_id = _mapped_optional_id(
                planned_page_ids,
                record.get("parent_planned_page_id"),
                "planned_pages.parent_planned_page_id",
            )
            session.add(restored)
        session.flush()

        for record in data.get("planning_records", []):
            planned_page_id = _mapped_id(
                planned_page_ids,
                record["planned_page_id"],
                "planning_records.planned_page_id",
            )
            _upsert(
                session,
                PlanningRecord,
                select(PlanningRecord).where(
                    PlanningRecord.planned_page_id == planned_page_id
                ),
                {**record, "planned_page_id": planned_page_id},
            )

        website_media_planning_record_ids: dict[int, int] = {}
        for record in sorted(
            data.get("website_media_planning_records", []),
            key=lambda value: value["version"],
        ):
            old_id = _record_id(record, "website_media_planning_records")
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "website_media_planning_records.site_plan_id",
            )
            restored = _upsert(
                session,
                WebsiteMediaPlanningRecord,
                select(WebsiteMediaPlanningRecord).where(
                    WebsiteMediaPlanningRecord.site_plan_id == site_plan_id,
                    WebsiteMediaPlanningRecord.version == record["version"],
                ),
                {
                    **_restore_page_media_planning_payload(
                        record,
                        website_ids=website_ids,
                        business_ids=business_ids,
                        site_plan_ids=site_plan_ids,
                        planned_page_ids=planned_page_ids,
                        generated_page_ids=generated_page_ids,
                        service_ids=service_ids,
                        city_ids=city_ids,
                        county_ids=county_ids,
                    ),
                    "website_id": _mapped_id(
                        website_ids,
                        record["website_id"],
                        "website_media_planning_records.website_id",
                    ),
                    "business_id": _mapped_id(
                        business_ids,
                        record["business_id"],
                        "website_media_planning_records.business_id",
                    ),
                    "site_plan_id": site_plan_id,
                    "replaces_record_id": _mapped_optional_id(
                        website_media_planning_record_ids,
                        record.get("replaces_record_id"),
                        "website_media_planning_records.replaces_record_id",
                    ),
                },
            )
            website_media_planning_record_ids[old_id] = _required_id(restored)

        planned_page_media_requirement_ids: dict[int, int] = {}
        for record in sorted(
            data.get("planned_page_media_requirements", []),
            key=lambda value: value["version"],
        ):
            old_id = _record_id(record, "planned_page_media_requirements")
            planned_page_id = _mapped_id(
                planned_page_ids,
                record["planned_page_id"],
                "planned_page_media_requirements.planned_page_id",
            )
            restored = _upsert(
                session,
                PlannedPageMediaRequirement,
                select(PlannedPageMediaRequirement).where(
                    PlannedPageMediaRequirement.planned_page_id == planned_page_id,
                    PlannedPageMediaRequirement.placement_key
                    == record["placement_key"],
                    PlannedPageMediaRequirement.version == record["version"],
                ),
                {
                    **record,
                    "website_id": _mapped_id(
                        website_ids,
                        record["website_id"],
                        "planned_page_media_requirements.website_id",
                    ),
                    "business_id": _mapped_id(
                        business_ids,
                        record["business_id"],
                        "planned_page_media_requirements.business_id",
                    ),
                    "site_plan_id": _mapped_id(
                        site_plan_ids,
                        record["site_plan_id"],
                        "planned_page_media_requirements.site_plan_id",
                    ),
                    "planned_page_id": planned_page_id,
                    "planning_record_id": _mapped_id(
                        website_media_planning_record_ids,
                        record["planning_record_id"],
                        "planned_page_media_requirements.planning_record_id",
                    ),
                    "replaces_requirement_id": _mapped_optional_id(
                        planned_page_media_requirement_ids,
                        record.get("replaces_requirement_id"),
                        "planned_page_media_requirements.replaces_requirement_id",
                    ),
                },
            )
            planned_page_media_requirement_ids[old_id] = _required_id(restored)

        for record in data.get("website_coverage_planning_records", []):
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "website_coverage_planning_records.site_plan_id",
            )
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_coverage_planning_records.website_id",
            )
            _upsert(
                session,
                WebsiteCoveragePlanningRecord,
                select(WebsiteCoveragePlanningRecord).where(
                    WebsiteCoveragePlanningRecord.site_plan_id == site_plan_id
                ),
                {**record, "site_plan_id": site_plan_id, "website_id": website_id},
            )

        for record in data.get("website_service_coverage_decisions", []):
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_service_coverage_decisions.website_id",
            )
            service_id = _mapped_id(
                service_ids,
                record["service_id"],
                "website_service_coverage_decisions.service_id",
            )
            _upsert(
                session,
                WebsiteServiceCoverageDecision,
                select(WebsiteServiceCoverageDecision).where(
                    WebsiteServiceCoverageDecision.website_id == website_id,
                    WebsiteServiceCoverageDecision.service_id == service_id,
                ),
                {**record, "website_id": website_id, "service_id": service_id},
            )

        for record in data.get("website_county_coverage_decisions", []):
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_county_coverage_decisions.website_id",
            )
            county_id = _mapped_id(
                county_ids,
                record["county_id"],
                "website_county_coverage_decisions.county_id",
            )
            _upsert(
                session,
                WebsiteCountyCoverageDecision,
                select(WebsiteCountyCoverageDecision).where(
                    WebsiteCountyCoverageDecision.website_id == website_id,
                    WebsiteCountyCoverageDecision.county_id == county_id,
                ),
                {**record, "website_id": website_id, "county_id": county_id},
            )

        for record in data.get("website_city_coverage_decisions", []):
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_city_coverage_decisions.website_id",
            )
            city_id = _mapped_id(
                city_ids,
                record["city_id"],
                "website_city_coverage_decisions.city_id",
            )
            _upsert(
                session,
                WebsiteCityCoverageDecision,
                select(WebsiteCityCoverageDecision).where(
                    WebsiteCityCoverageDecision.website_id == website_id,
                    WebsiteCityCoverageDecision.city_id == city_id,
                ),
                {**record, "website_id": website_id, "city_id": city_id},
            )

        for record in data.get("website_service_city_coverage_decisions", []):
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_service_city_coverage_decisions.website_id",
            )
            service_id = _mapped_id(
                service_ids,
                record["service_id"],
                "website_service_city_coverage_decisions.service_id",
            )
            city_id = _mapped_id(
                city_ids,
                record["city_id"],
                "website_service_city_coverage_decisions.city_id",
            )
            _upsert(
                session,
                WebsiteServiceCityCoverageDecision,
                select(WebsiteServiceCityCoverageDecision).where(
                    WebsiteServiceCityCoverageDecision.website_id == website_id,
                    WebsiteServiceCityCoverageDecision.service_id == service_id,
                    WebsiteServiceCityCoverageDecision.city_id == city_id,
                ),
                {
                    **record,
                    "website_id": website_id,
                    "service_id": service_id,
                    "city_id": city_id,
                },
            )

        for record in data.get("website_service_county_coverage_decisions", []):
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_service_county_coverage_decisions.website_id",
            )
            service_id = _mapped_id(
                service_ids,
                record["service_id"],
                "website_service_county_coverage_decisions.service_id",
            )
            county_id = _mapped_id(
                county_ids,
                record["county_id"],
                "website_service_county_coverage_decisions.county_id",
            )
            _upsert(
                session,
                WebsiteServiceCountyCoverageDecision,
                select(WebsiteServiceCountyCoverageDecision).where(
                    WebsiteServiceCountyCoverageDecision.website_id == website_id,
                    WebsiteServiceCountyCoverageDecision.service_id == service_id,
                    WebsiteServiceCountyCoverageDecision.county_id == county_id,
                ),
                {
                    **record,
                    "website_id": website_id,
                    "service_id": service_id,
                    "county_id": county_id,
                },
            )
        for record in data.get("supporting_page_authorizations", []):
            website_id = _mapped_id(
                website_ids, record["website_id"],
                "supporting_page_authorizations.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids, record["site_plan_id"],
                "supporting_page_authorizations.site_plan_id",
            )
            planned_page_id = _mapped_id(
                planned_page_ids, record["planned_page_id"],
                "supporting_page_authorizations.planned_page_id",
            )
            _upsert(
                session,
                SupportingPageAuthorization,
                select(SupportingPageAuthorization).where(
                    SupportingPageAuthorization.planned_page_id
                    == planned_page_id
                ),
                {
                    **record,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                    "planned_page_id": planned_page_id,
                },
            )

        for record in data.get("pre_draft_distinctness_briefs", []):
            website_id = _mapped_id(
                website_ids, record["website_id"],
                "pre_draft_distinctness_briefs.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids, record["site_plan_id"],
                "pre_draft_distinctness_briefs.site_plan_id",
            )
            planned_page_id = _mapped_id(
                planned_page_ids, record["planned_page_id"],
                "pre_draft_distinctness_briefs.planned_page_id",
            )
            _upsert(
                session,
                PreDraftDistinctnessBrief,
                select(PreDraftDistinctnessBrief).where(
                    PreDraftDistinctnessBrief.planned_page_id
                    == planned_page_id
                ),
                {
                    **record,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                    "planned_page_id": planned_page_id,
                },
            )

        assessment_ids: dict[int, int] = {}
        for record in data.get("drafting_eligibility_assessments", []):
            old_id = _record_id(record, "drafting_eligibility_assessments")
            website_id = _mapped_id(
                website_ids, record["website_id"],
                "drafting_eligibility_assessments.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids, record["site_plan_id"],
                "drafting_eligibility_assessments.site_plan_id",
            )
            planned_page_id = _mapped_id(
                planned_page_ids, record["planned_page_id"],
                "drafting_eligibility_assessments.planned_page_id",
            )
            restored = _upsert(
                session,
                DraftingEligibilityAssessment,
                select(DraftingEligibilityAssessment).where(
                    DraftingEligibilityAssessment.planned_page_id
                    == planned_page_id
                ),
                {
                    **record,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                    "planned_page_id": planned_page_id,
                },
            )
            assessment_ids[old_id] = _required_id(restored)

        for record in data.get("drafting_eligibility_dispositions", []):
            website_id = _mapped_id(
                website_ids, record["website_id"],
                "drafting_eligibility_dispositions.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids, record["site_plan_id"],
                "drafting_eligibility_dispositions.site_plan_id",
            )
            planned_page_id = _mapped_id(
                planned_page_ids, record["planned_page_id"],
                "drafting_eligibility_dispositions.planned_page_id",
            )
            assessment_id = _mapped_id(
                assessment_ids, record["assessment_id"],
                "drafting_eligibility_dispositions.assessment_id",
            )
            _upsert(
                session,
                DraftingEligibilityDisposition,
                select(DraftingEligibilityDisposition).where(
                    DraftingEligibilityDisposition.planned_page_id
                    == planned_page_id
                ),
                {
                    **record,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                    "planned_page_id": planned_page_id,
                    "assessment_id": assessment_id,
                },
            )

        generation_run_ids: dict[int, int] = {}
        for record in data.get("website_draft_generation_runs", []):
            old_id = _record_id(record, "website_draft_generation_runs")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_draft_generation_runs.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "website_draft_generation_runs.site_plan_id",
            )
            restored = _upsert(
                session,
                WebsiteDraftGenerationRun,
                select(WebsiteDraftGenerationRun).where(
                    WebsiteDraftGenerationRun.site_plan_id == site_plan_id,
                    WebsiteDraftGenerationRun.manifest_hash
                    == record["manifest_hash"],
                ),
                {
                    **record,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                },
            )
            generation_run_ids[old_id] = _required_id(restored)

        for record in data.get("website_draft_generation_items", []):
            run_id = _mapped_id(
                generation_run_ids,
                record["run_id"],
                "website_draft_generation_items.run_id",
            )
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_draft_generation_items.website_id",
            )
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "website_draft_generation_items.site_plan_id",
            )
            planned_page_id = _mapped_optional_id(
                planned_page_ids,
                record.get("planned_page_id"),
                "website_draft_generation_items.planned_page_id",
            )
            generated_page_id = _mapped_optional_id(
                generated_page_ids,
                record.get("generated_page_id"),
                "website_draft_generation_items.generated_page_id",
            )
            assessment_id = _mapped_optional_id(
                assessment_ids,
                record.get("assessment_id"),
                "website_draft_generation_items.assessment_id",
            )
            _upsert(
                session,
                WebsiteDraftGenerationItem,
                select(WebsiteDraftGenerationItem).where(
                    WebsiteDraftGenerationItem.run_id == run_id,
                    WebsiteDraftGenerationItem.inventory_key
                    == record["inventory_key"],
                ),
                {
                    **record,
                    "run_id": run_id,
                    "website_id": website_id,
                    "site_plan_id": site_plan_id,
                    "planned_page_id": planned_page_id,
                    "generated_page_id": generated_page_id,
                    "assessment_id": assessment_id,
                },
            )

        navigation_set_ids: dict[int, int] = {}
        for record in data.get("navigation_sets", []):
            old_id = _record_id(record, "navigation_sets")
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "navigation_sets.site_plan_id",
            )
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "navigation_sets.website_id",
            )
            restored = _upsert(
                session,
                NavigationSet,
                select(NavigationSet).where(
                    NavigationSet.site_plan_id == site_plan_id,
                    NavigationSet.set_type == record["set_type"],
                ),
                {
                    **record,
                    "site_plan_id": site_plan_id,
                    "website_id": website_id,
                    "source_suggestion_key": _remap_site_connection_suggestion_key(
                        record.get("source_suggestion_key"),
                        planned_page_ids,
                    ),
                },
            )
            navigation_set_ids[old_id] = _required_id(restored)

        for record in data.get("site_connection_planning_records", []):
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "site_connection_planning_records.site_plan_id",
            )
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "site_connection_planning_records.website_id",
            )
            _upsert(
                session,
                SiteConnectionPlanningRecord,
                select(SiteConnectionPlanningRecord).where(
                    SiteConnectionPlanningRecord.site_plan_id == site_plan_id
                ),
                {
                    **_restore_site_connection_planning_payload(
                        record,
                        planned_page_ids,
                    ),
                    "site_plan_id": site_plan_id,
                    "website_id": website_id,
                },
            )

        navigation_item_ids: dict[int, int] = {}
        pending_navigation_items: list[
            tuple[dict[str, Any], NavigationItem]
        ] = []
        for record in data.get("navigation_items", []):
            old_id = _record_id(record, "navigation_items")
            restored = _upsert(
                session,
                NavigationItem,
                select(NavigationItem).where(
                    NavigationItem.navigation_set_id
                    == _mapped_id(
                        navigation_set_ids,
                        record["navigation_set_id"],
                        "navigation_items.navigation_set_id",
                    ),
                    NavigationItem.target_planned_page_id
                    == _mapped_id(
                        planned_page_ids,
                        record["target_planned_page_id"],
                        "navigation_items.target_planned_page_id",
                    ),
                ),
                {
                    **record,
                    "website_id": _mapped_id(
                        website_ids,
                        record["website_id"],
                        "navigation_items.website_id",
                    ),
                    "site_plan_id": _mapped_id(
                        site_plan_ids,
                        record["site_plan_id"],
                        "navigation_items.site_plan_id",
                    ),
                    "navigation_set_id": _mapped_id(
                        navigation_set_ids,
                        record["navigation_set_id"],
                        "navigation_items.navigation_set_id",
                    ),
                    "target_planned_page_id": _mapped_id(
                        planned_page_ids,
                        record["target_planned_page_id"],
                        "navigation_items.target_planned_page_id",
                    ),
                    "parent_navigation_item_id": None,
                    "source_suggestion_key": _remap_site_connection_suggestion_key(
                        record.get("source_suggestion_key"),
                        planned_page_ids,
                    ),
                },
            )
            navigation_item_ids[old_id] = _required_id(restored)
            pending_navigation_items.append((record, restored))
        for record, restored in pending_navigation_items:
            restored.parent_navigation_item_id = _mapped_optional_id(
                navigation_item_ids,
                record.get("parent_navigation_item_id"),
                "navigation_items.parent_navigation_item_id",
            )
            session.add(restored)
        session.flush()

        internal_link_intent_ids: dict[int, int] = {}
        for record in data.get("internal_link_intents", []):
            old_id = _record_id(record, "internal_link_intents")
            site_plan_id = _mapped_id(
                site_plan_ids,
                record["site_plan_id"],
                "internal_link_intents.site_plan_id",
            )
            source_id = _mapped_id(
                planned_page_ids,
                record["source_planned_page_id"],
                "internal_link_intents.source_planned_page_id",
            )
            target_id = _mapped_id(
                planned_page_ids,
                record["target_planned_page_id"],
                "internal_link_intents.target_planned_page_id",
            )
            restored = _upsert(
                session,
                InternalLinkIntent,
                select(InternalLinkIntent).where(
                    InternalLinkIntent.site_plan_id == site_plan_id,
                    InternalLinkIntent.source_planned_page_id == source_id,
                    InternalLinkIntent.target_planned_page_id == target_id,
                    InternalLinkIntent.relationship_type
                    == record["relationship_type"],
                ),
                {
                    **record,
                    "website_id": _mapped_id(
                        website_ids,
                        record["website_id"],
                        "internal_link_intents.website_id",
                    ),
                    "site_plan_id": site_plan_id,
                    "source_planned_page_id": source_id,
                    "target_planned_page_id": target_id,
                    "source_suggestion_key": _remap_site_connection_suggestion_key(
                        record.get("source_suggestion_key"),
                        planned_page_ids,
                    ),
                },
            )
            internal_link_intent_ids[old_id] = _required_id(restored)

        for record in data.get("semantic_component_definitions", []):
            _upsert(
                session,
                SemanticComponentDefinition,
                select(SemanticComponentDefinition).where(
                    SemanticComponentDefinition.component_key == record["component_key"],
                    SemanticComponentDefinition.contract_version == record["contract_version"],
                ),
                record,
            )

        page_composition_ids: dict[int, int] = {}
        for record in data.get("page_compositions", []):
            old_composition_id = _record_id(record, "page_compositions")
            planned_page_id = _mapped_id(
                planned_page_ids,
                record["planned_page_id"],
                "page_compositions.planned_page_id",
            )
            restored_snapshot = _restore_theme_source_binding(
                record.get("source_snapshot", {}),
                website_ids=website_ids,
                theme_ids=theme_ids,
                selection_ids=website_theme_selection_ids,
            )
            restored_source_hash = _canonical_json_hash(restored_snapshot)
            if preserve_source_ids:
                # A clean exact-ID restore must preserve the durable composition
                # identity from the accepted backup.  Re-hashing an unchanged
                # historical snapshot with newer canonicalization code would
                # manufacture a different source identity and force an
                # unnecessary composition/QA refresh.
                restored_snapshot = deepcopy(record.get("source_snapshot", {}))
                restored_source_hash = record["source_hash"]
            restored_composition = _upsert(
                session,
                PageComposition,
                select(PageComposition).where(
                    PageComposition.planned_page_id == planned_page_id
                ),
                {
                    **record,
                    "source_snapshot": restored_snapshot,
                    "source_hash": restored_source_hash,
                    "website_id": _mapped_id(
                        website_ids, record["website_id"], "page_compositions.website_id"
                    ),
                    "site_plan_id": _mapped_id(
                        site_plan_ids, record["site_plan_id"], "page_compositions.site_plan_id"
                    ),
                    "planned_page_id": planned_page_id,
                    "generated_page_id": _mapped_id(
                        generated_page_ids,
                        record["generated_page_id"],
                        "page_compositions.generated_page_id",
                    ),
                },
            )
            page_composition_ids[old_composition_id] = _required_id(
                restored_composition
            )

        theme_family_ids: dict[int, int] = {}
        for record in data.get("theme_families", []):
            old_id = _record_id(record, "theme_families")
            restored = _restore_immutable_record(
                session,
                ThemeFamily,
                select(ThemeFamily).where(
                    ThemeFamily.family_key == record["family_key"]
                ),
                record,
                label="Theme Family",
            )
            theme_family_ids[old_id] = _required_id(restored)

        theme_family_version_ids: dict[int, int] = {}
        pending_family_versions = list(data.get("theme_family_versions", []))
        while pending_family_versions:
            deferred: list[dict[str, Any]] = []
            for record in pending_family_versions:
                predecessor_id = record.get("supersedes_theme_family_version_id")
                if (
                    predecessor_id is not None
                    and predecessor_id not in theme_family_version_ids
                ):
                    deferred.append(record)
                    continue
                old_id = _record_id(record, "theme_family_versions")
                family_id = _mapped_id(
                    theme_family_ids,
                    record["theme_family_id"],
                    "theme_family_versions.theme_family_id",
                )
                restored_record = {
                    **record,
                    "theme_family_id": family_id,
                    "supersedes_theme_family_version_id": _mapped_optional_id(
                        theme_family_version_ids,
                        predecessor_id,
                        "theme_family_versions.supersedes_theme_family_version_id",
                    ),
                }
                restored_record["integrity_fingerprint"] = _canonical_json_hash(
                    _theme_family_version_fingerprint_payload(restored_record)
                )
                restored = _restore_immutable_record(
                    session,
                    ThemeFamilyVersion,
                    select(ThemeFamilyVersion).where(
                        ThemeFamilyVersion.theme_family_id == family_id,
                        ThemeFamilyVersion.version == record["version"],
                    ),
                    restored_record,
                    label="Theme Family Version",
                )
                theme_family_version_ids[old_id] = _required_id(restored)
            if len(deferred) == len(pending_family_versions):
                raise BackupValidationError(
                    "Theme Family Version restore lineage is cyclic or unresolved."
                )
            pending_family_versions = deferred

        website_theme_configuration_ids: dict[int, int] = {}
        pending_theme_configurations = list(
            data.get("website_theme_configurations", [])
        )
        while pending_theme_configurations:
            deferred = []
            for record in pending_theme_configurations:
                predecessor_id = record.get("supersedes_configuration_id")
                if (
                    predecessor_id is not None
                    and predecessor_id not in website_theme_configuration_ids
                ):
                    deferred.append(record)
                    continue
                old_id = _record_id(record, "website_theme_configurations")
                website_id = _mapped_id(
                    website_ids,
                    record["website_id"],
                    "website_theme_configurations.website_id",
                )
                family_version_id = _mapped_id(
                    theme_family_version_ids,
                    record["theme_family_version_id"],
                    "website_theme_configurations.theme_family_version_id",
                )
                restored_record = {
                    **record,
                    "website_id": website_id,
                    "business_id": _mapped_id(
                        business_ids,
                        record["business_id"],
                        "website_theme_configurations.business_id",
                    ),
                    "theme_family_version_id": family_version_id,
                    "materialized_theme_id": _mapped_optional_id(
                        theme_ids,
                        record.get("materialized_theme_id"),
                        "website_theme_configurations.materialized_theme_id",
                    ),
                    "website_theme_selection_id": _mapped_optional_id(
                        website_theme_selection_ids,
                        record.get("website_theme_selection_id"),
                        "website_theme_configurations.website_theme_selection_id",
                    ),
                    "supersedes_configuration_id": _mapped_optional_id(
                        website_theme_configuration_ids,
                        predecessor_id,
                        "website_theme_configurations.supersedes_configuration_id",
                    ),
                }
                restored_record["integrity_fingerprint"] = _canonical_json_hash(
                    _website_theme_configuration_fingerprint_payload(
                        restored_record
                    )
                )
                restored = _restore_immutable_record(
                    session,
                    WebsiteThemeConfiguration,
                    select(WebsiteThemeConfiguration).where(
                        WebsiteThemeConfiguration.website_id == website_id,
                        WebsiteThemeConfiguration.theme_family_version_id
                        == family_version_id,
                        WebsiteThemeConfiguration.configuration_key
                        == record["configuration_key"],
                        WebsiteThemeConfiguration.version == record["version"],
                    ),
                    restored_record,
                    label="Website Theme configuration",
                )
                website_theme_configuration_ids[old_id] = _required_id(restored)
            if len(deferred) == len(pending_theme_configurations):
                raise BackupValidationError(
                    "Website Theme configuration restore lineage is cyclic or unresolved."
                )
            pending_theme_configurations = deferred

        theme_component_configuration_ids: dict[int, int] = {}
        pending_component_configurations = list(
            data.get("website_theme_component_configurations", [])
        )
        component_dependency_fields = (
            "destination_component_configuration_id",
            "overrides_component_configuration_id",
            "supersedes_component_configuration_id",
        )
        while pending_component_configurations:
            deferred = []
            for record in pending_component_configurations:
                if any(
                    record.get(field) is not None
                    and record[field] not in theme_component_configuration_ids
                    for field in component_dependency_fields
                ):
                    deferred.append(record)
                    continue
                old_id = _record_id(
                    record,
                    "website_theme_component_configurations",
                )
                configuration_id = _mapped_id(
                    website_theme_configuration_ids,
                    record["website_theme_configuration_id"],
                    "website_theme_component_configurations.website_theme_configuration_id",
                )
                restored_record = {
                    **record,
                    "website_theme_configuration_id": configuration_id,
                    "website_id": _mapped_id(
                        website_ids,
                        record["website_id"],
                        "website_theme_component_configurations.website_id",
                    ),
                    "planned_page_id": _mapped_optional_id(
                        planned_page_ids,
                        record.get("planned_page_id"),
                        "website_theme_component_configurations.planned_page_id",
                    ),
                    "theme_family_version_id": _mapped_id(
                        theme_family_version_ids,
                        record["theme_family_version_id"],
                        "website_theme_component_configurations.theme_family_version_id",
                    ),
                }
                for field in component_dependency_fields:
                    restored_record[field] = _mapped_optional_id(
                        theme_component_configuration_ids,
                        record.get(field),
                        f"website_theme_component_configurations.{field}",
                    )
                restored_record["integrity_fingerprint"] = _canonical_json_hash(
                    _theme_component_configuration_fingerprint_payload(
                        restored_record
                    )
                )
                restored = _restore_immutable_record(
                    session,
                    WebsiteThemeComponentConfiguration,
                    select(WebsiteThemeComponentConfiguration).where(
                        WebsiteThemeComponentConfiguration.website_theme_configuration_id
                        == configuration_id,
                        WebsiteThemeComponentConfiguration.component_instance_key
                        == record["component_instance_key"],
                        WebsiteThemeComponentConfiguration.revision
                        == record["revision"],
                    ),
                    restored_record,
                    label="Website Theme component configuration",
                )
                theme_component_configuration_ids[old_id] = _required_id(restored)
            if len(deferred) == len(pending_component_configurations):
                raise BackupValidationError(
                    "Theme component restore dependencies are cyclic or unresolved."
                )
            pending_component_configurations = deferred

        for record in data.get("theme_configuration_audits", []):
            restored_record = {
                **record,
                "theme_family_id": _mapped_optional_id(
                    theme_family_ids,
                    record.get("theme_family_id"),
                    "theme_configuration_audits.theme_family_id",
                ),
                "theme_family_version_id": _mapped_optional_id(
                    theme_family_version_ids,
                    record.get("theme_family_version_id"),
                    "theme_configuration_audits.theme_family_version_id",
                ),
                "website_theme_configuration_id": _mapped_optional_id(
                    website_theme_configuration_ids,
                    record.get("website_theme_configuration_id"),
                    "theme_configuration_audits.website_theme_configuration_id",
                ),
                "component_configuration_id": _mapped_optional_id(
                    theme_component_configuration_ids,
                    record.get("component_configuration_id"),
                    "theme_configuration_audits.component_configuration_id",
                ),
                "snapshot": _restore_theme_configuration_audit_snapshot(
                    record.get("snapshot"),
                    website_ids=website_ids,
                    business_ids=business_ids,
                    planned_page_ids=planned_page_ids,
                    theme_ids=theme_ids,
                    selection_ids=website_theme_selection_ids,
                    family_ids=theme_family_ids,
                    family_version_ids=theme_family_version_ids,
                    configuration_ids=website_theme_configuration_ids,
                    component_ids=theme_component_configuration_ids,
                ),
            }
            restored_record["snapshot_hash"] = _canonical_json_hash(
                _theme_configuration_audit_hash_payload(restored_record)
            )
            _restore_immutable_record(
                session,
                ThemeConfigurationAudit,
                select(ThemeConfigurationAudit).where(
                    ThemeConfigurationAudit.snapshot_hash
                    == restored_record["snapshot_hash"]
                ),
                restored_record,
                label="Theme configuration audit",
            )

        if any(
            data.get(group)
            for group in (
                "theme_families",
                "theme_family_versions",
                "website_theme_configurations",
                "website_theme_component_configurations",
                "theme_configuration_audits",
            )
        ):
            from app.services.theme_configurations import (
                validate_theme_configuration_records,
            )

            validate_theme_configuration_records(session)

        from app.services.form_delivery_modes import (
            form_delivery_configuration_audit_hash,
            form_delivery_mode_fingerprint,
            form_recipient_fingerprint,
        )
        from app.services.form_delivery_outbox import (
            form_delivery_attempt_fingerprint,
            form_submission_envelope_fingerprint,
        )

        form_delivery_mode_ids: dict[int, int] = {}
        _require_restore_compatible_form_delivery_mode_prefixes(
            session,
            data.get("website_form_delivery_mode_revisions", []),
            website_ids=website_ids,
        )
        for record in sorted(
            data.get("website_form_delivery_mode_revisions", []),
            key=lambda item: (
                item["website_id"],
                item["form_instance_key"],
                item["revision"],
            ),
        ):
            old_id = _record_id(
                record,
                "website_form_delivery_mode_revisions",
            )
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_form_delivery_mode_revisions.website_id",
            )
            restored_record = {
                **record,
                "website_id": website_id,
                "form_component_configuration_id": _mapped_id(
                    theme_component_configuration_ids,
                    record["form_component_configuration_id"],
                    "website_form_delivery_mode_revisions.form_component_configuration_id",
                ),
                "supersedes_delivery_mode_revision_id": _mapped_optional_id(
                    form_delivery_mode_ids,
                    record.get("supersedes_delivery_mode_revision_id"),
                    "website_form_delivery_mode_revisions.supersedes_delivery_mode_revision_id",
                ),
            }
            restored_record["integrity_fingerprint"] = (
                form_delivery_mode_fingerprint(restored_record)
            )
            restored = _restore_immutable_record(
                session,
                WebsiteFormDeliveryModeRevision,
                select(WebsiteFormDeliveryModeRevision).where(
                    WebsiteFormDeliveryModeRevision.website_id == website_id,
                    WebsiteFormDeliveryModeRevision.form_instance_key
                    == record["form_instance_key"],
                    WebsiteFormDeliveryModeRevision.revision == record["revision"],
                ),
                restored_record,
                label="Website form-delivery mode revision",
            )
            form_delivery_mode_ids[old_id] = _required_id(restored)

        form_recipient_revision_ids: dict[int, int] = {}
        _require_restore_compatible_form_recipient_prefixes(
            session,
            data.get("website_form_recipient_revisions", []),
            website_ids=website_ids,
        )
        for record in sorted(
            data.get("website_form_recipient_revisions", []),
            key=lambda item: (
                item["website_id"],
                item["form_instance_key"],
                item["recipient_key"],
                item["revision"],
            ),
        ):
            old_id = _record_id(record, "website_form_recipient_revisions")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "website_form_recipient_revisions.website_id",
            )
            restored_record = {
                **record,
                "delivery_mode_revision_id": _mapped_id(
                    form_delivery_mode_ids,
                    record["delivery_mode_revision_id"],
                    "website_form_recipient_revisions.delivery_mode_revision_id",
                ),
                "website_id": website_id,
                "form_component_configuration_id": _mapped_id(
                    theme_component_configuration_ids,
                    record["form_component_configuration_id"],
                    "website_form_recipient_revisions.form_component_configuration_id",
                ),
                "supersedes_recipient_revision_id": _mapped_optional_id(
                    form_recipient_revision_ids,
                    record.get("supersedes_recipient_revision_id"),
                    "website_form_recipient_revisions.supersedes_recipient_revision_id",
                ),
            }
            restored_record["integrity_fingerprint"] = form_recipient_fingerprint(
                restored_record
            )
            restored = _restore_immutable_record(
                session,
                WebsiteFormRecipientRevision,
                select(WebsiteFormRecipientRevision).where(
                    WebsiteFormRecipientRevision.website_id == website_id,
                    WebsiteFormRecipientRevision.form_instance_key
                    == record["form_instance_key"],
                    WebsiteFormRecipientRevision.recipient_key
                    == record["recipient_key"],
                    WebsiteFormRecipientRevision.revision == record["revision"],
                ),
                restored_record,
                label="Website form-recipient revision",
            )
            form_recipient_revision_ids[old_id] = _required_id(restored)

        form_submission_envelope_ids: dict[int, int] = {}
        for record in data.get("form_submission_envelopes", []):
            old_id = _record_id(record, "form_submission_envelopes")
            website_id = _mapped_id(
                website_ids,
                record["website_id"],
                "form_submission_envelopes.website_id",
            )
            component_id = _mapped_id(
                theme_component_configuration_ids,
                record["form_component_configuration_id"],
                "form_submission_envelopes.form_component_configuration_id",
            )
            restored_record = {
                **record,
                "website_id": website_id,
                "form_component_configuration_id": component_id,
                "delivery_mode_revision_id": _mapped_id(
                    form_delivery_mode_ids,
                    record["delivery_mode_revision_id"],
                    "form_submission_envelopes.delivery_mode_revision_id",
                ),
            }
            restored_record["integrity_fingerprint"] = (
                form_submission_envelope_fingerprint(restored_record)
            )
            restored = _restore_immutable_record(
                session,
                FormSubmissionEnvelope,
                select(FormSubmissionEnvelope).where(
                    FormSubmissionEnvelope.website_id == website_id,
                    FormSubmissionEnvelope.form_component_configuration_id
                    == component_id,
                    FormSubmissionEnvelope.idempotency_digest
                    == record["idempotency_digest"],
                ),
                restored_record,
                label="form-submission envelope",
            )
            form_submission_envelope_ids[old_id] = _required_id(restored)

        form_delivery_outbox_ids: dict[int, int] = {}
        for record in data.get("form_delivery_outbox_records", []):
            old_id = _record_id(record, "form_delivery_outbox_records")
            envelope_id = _mapped_id(
                form_submission_envelope_ids,
                record["envelope_id"],
                "form_delivery_outbox_records.envelope_id",
            )
            restored_record = {
                **record,
                "envelope_id": envelope_id,
                "delivery_mode_revision_id": _mapped_id(
                    form_delivery_mode_ids,
                    record["delivery_mode_revision_id"],
                    "form_delivery_outbox_records.delivery_mode_revision_id",
                ),
            }
            restored = _restore_immutable_record(
                session,
                FormDeliveryOutbox,
                select(FormDeliveryOutbox).where(
                    FormDeliveryOutbox.envelope_id == envelope_id
                ),
                restored_record,
                label="form-delivery outbox record",
            )
            form_delivery_outbox_ids[old_id] = _required_id(restored)

        for record in sorted(
            data.get("form_delivery_attempts", []),
            key=lambda item: (item["outbox_id"], item["attempt_number"]),
        ):
            outbox_id = _mapped_id(
                form_delivery_outbox_ids,
                record["outbox_id"],
                "form_delivery_attempts.outbox_id",
            )
            restored_record = {**record, "outbox_id": outbox_id}
            restored_record["integrity_fingerprint"] = (
                form_delivery_attempt_fingerprint(restored_record)
            )
            _restore_immutable_record(
                session,
                FormDeliveryAttempt,
                select(FormDeliveryAttempt).where(
                    FormDeliveryAttempt.outbox_id == outbox_id,
                    FormDeliveryAttempt.attempt_number
                    == record["attempt_number"],
                ),
                restored_record,
                label="form-delivery attempt",
            )

        for record in data.get("form_delivery_configuration_audits", []):
            restored_record = {
                **record,
                "delivery_mode_revision_id": _mapped_optional_id(
                    form_delivery_mode_ids,
                    record.get("delivery_mode_revision_id"),
                    "form_delivery_configuration_audits.delivery_mode_revision_id",
                ),
                "recipient_revision_id": _mapped_optional_id(
                    form_recipient_revision_ids,
                    record.get("recipient_revision_id"),
                    "form_delivery_configuration_audits.recipient_revision_id",
                ),
                "snapshot": _restore_form_delivery_audit_snapshot(
                    record.get("snapshot"),
                    website_ids=website_ids,
                    component_ids=theme_component_configuration_ids,
                    mode_revision_ids=form_delivery_mode_ids,
                    recipient_revision_ids=form_recipient_revision_ids,
                ),
            }
            restored_record["snapshot_hash"] = (
                form_delivery_configuration_audit_hash(restored_record)
            )
            if restored_record["delivery_mode_revision_id"] is not None:
                audit_target = select(FormDeliveryConfigurationAudit).where(
                    FormDeliveryConfigurationAudit.delivery_mode_revision_id
                    == restored_record["delivery_mode_revision_id"],
                    FormDeliveryConfigurationAudit.recipient_revision_id.is_(None),
                )
            else:
                audit_target = select(FormDeliveryConfigurationAudit).where(
                    FormDeliveryConfigurationAudit.recipient_revision_id
                    == restored_record["recipient_revision_id"],
                    FormDeliveryConfigurationAudit.delivery_mode_revision_id.is_(None),
                )
            _restore_immutable_record(
                session,
                FormDeliveryConfigurationAudit,
                audit_target,
                restored_record,
                label="form-delivery configuration audit",
            )

        if any(data.get(group) for group in FORM_DELIVERY_BACKUP_GROUPS):
            from app.services.form_delivery_modes import (
                validate_form_delivery_records,
            )

            validate_form_delivery_records(session)

        backup_version = payload["metadata"]["version"]
        backed_connection_plan_ids = {
            record["site_plan_id"]
            for record in data.get("site_connection_planning_records", [])
        }
        backed_navigation_set_types = {
            old_plan_id: {
                record["set_type"]
                for record in data.get("navigation_sets", [])
                if record["site_plan_id"] == old_plan_id
            }
            for old_plan_id in site_plan_ids
        }
        connection_foundation_plan_ids = {
            old_plan_id
            for old_plan_id in site_plan_ids
            if _backup_version_before(backup_version, "0.44")
            or old_plan_id not in backed_connection_plan_ids
            or backed_navigation_set_types[old_plan_id]
            != {"primary", "utility", "footer"}
        }
        if connection_foundation_plan_ids:
            from app.services.site_connections import (
                ensure_site_connection_foundation,
            )

            for old_plan_id in sorted(connection_foundation_plan_ids):
                restored_plan_id = site_plan_ids[old_plan_id]
                restored_plan = session.get(SitePlan, restored_plan_id)
                if restored_plan:
                    ensure_site_connection_foundation(
                        session,
                        restored_plan,
                        commit=False,
                    )
        backed_coverage_plan_ids = {
            record["site_plan_id"]
            for record in data.get("website_coverage_planning_records", [])
        }
        coverage_foundation_plan_ids = {
            old_plan_id
            for old_plan_id in site_plan_ids
            if _backup_version_before(backup_version, "0.45")
            or old_plan_id not in backed_coverage_plan_ids
        }
        if coverage_foundation_plan_ids:
            from app.services.site_coverage import ensure_coverage_foundation

            for old_plan_id in sorted(coverage_foundation_plan_ids):
                restored_plan_id = site_plan_ids[old_plan_id]
                restored_plan = session.get(SitePlan, restored_plan_id)
                if restored_plan:
                    ensure_coverage_foundation(
                        session,
                        restored_plan,
                        commit=False,
                    )

        pending_approval_qa_snapshots: list[
            tuple[dict[str, Any], ApprovalAudit]
        ] = []
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
                "qa_result_snapshot": _restore_qa_page_identity(
                    record.get("qa_result_snapshot"),
                    generated_page_ids=generated_page_ids,
                    field="approval_audits.qa_result_snapshot.page_id",
                ),
                "approved_at": approved_at,
                "qa_checked_at": _datetime_value(
                    record["qa_checked_at"],
                    "approval_audits.qa_checked_at",
                ),
            }
            restored_audit = _upsert(
                session,
                ApprovalAudit,
                select(ApprovalAudit).where(
                    ApprovalAudit.generated_page_id == page_id,
                    ApprovalAudit.approved_at == approved_at,
                    ApprovalAudit.draft_hash_at_approval == record["draft_hash_at_approval"],
                ),
                restored_record,
            )
            pending_approval_qa_snapshots.append(
                (record["qa_result_snapshot"], restored_audit)
            )

        generated_page_revision_ids: dict[int, int] = {}
        for record in data["page_revisions"]:
            old_revision_id = _record_id(record, "page_revisions")
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
            restored_revision = _upsert(
                session,
                GeneratedPageRevision,
                select(GeneratedPageRevision).where(
                    GeneratedPageRevision.generated_page_id == page_id,
                    GeneratedPageRevision.created_at == created_at,
                    GeneratedPageRevision.draft_hash_after == record["draft_hash_after"],
                ),
                restored_record,
            )
            generated_page_revision_ids[old_revision_id] = _required_id(
                restored_revision
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
        for record in sorted(
            data["image_metadata"],
            key=lambda value: value.get("media_version") or 0,
        ):
            old_id = _record_id(record, "image_metadata")
            business_id = _mapped_id(business_ids, record["business_id"], "image_metadata.business_id")
            website_id = _mapped_optional_id(
                website_ids,
                record.get("website_id"),
                "image_metadata.website_id",
            )
            restored_record = {
                **record,
                "business_id": business_id,
                "website_id": website_id,
                "service_id": _mapped_optional_id(service_ids, record.get("service_id"), "image_metadata.service_id"),
                "city_id": _mapped_optional_id(city_ids, record.get("city_id"), "image_metadata.city_id"),
                "county_id": _mapped_optional_id(county_ids, record.get("county_id"), "image_metadata.county_id"),
                "replaces_image_metadata_id": _mapped_optional_id(
                    image_metadata_ids,
                    record.get("replaces_image_metadata_id"),
                    "image_metadata.replaces_image_metadata_id",
                ),
            }
            if (
                website_id is not None
                and record.get("media_key") is not None
                and record.get("media_version") is not None
            ):
                image_statement = select(ImageMetadata).where(
                    ImageMetadata.website_id == website_id,
                    ImageMetadata.media_key == record["media_key"],
                    ImageMetadata.media_version == record["media_version"],
                )
            else:
                image_statement = select(ImageMetadata).where(
                    ImageMetadata.business_id == business_id,
                    ImageMetadata.file_name == record["file_name"],
                )
            restored = _upsert(
                session,
                ImageMetadata,
                image_statement,
                restored_record,
            )
            image_metadata_ids[old_id] = _required_id(restored)

        page_image_assignment_ids: dict[int, int] = {}
        for record in sorted(
            data["page_image_assignments"],
            key=lambda value: value.get("assignment_version") or 0,
        ):
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
                "website_id": _mapped_optional_id(
                    website_ids,
                    record.get("website_id"),
                    "page_image_assignments.website_id",
                ),
                "site_plan_id": _mapped_optional_id(
                    site_plan_ids,
                    record.get("site_plan_id"),
                    "page_image_assignments.site_plan_id",
                ),
                "planned_page_id": _mapped_optional_id(
                    planned_page_ids,
                    record.get("planned_page_id"),
                    "page_image_assignments.planned_page_id",
                ),
                "media_requirement_id": _mapped_optional_id(
                    planned_page_media_requirement_ids,
                    record.get("media_requirement_id"),
                    "page_image_assignments.media_requirement_id",
                ),
                "replaces_page_image_assignment_id": _mapped_optional_id(
                    page_image_assignment_ids,
                    record.get("replaces_page_image_assignment_id"),
                    "page_image_assignments.replaces_page_image_assignment_id",
                ),
            }
            if (
                restored_record["media_requirement_id"] is not None
                and record.get("assignment_version") is not None
            ):
                assignment_statement = select(PageImageAssignment).where(
                    PageImageAssignment.media_requirement_id
                    == restored_record["media_requirement_id"],
                    PageImageAssignment.assignment_version
                    == record["assignment_version"],
                )
            else:
                assignment_statement = select(PageImageAssignment).where(
                    PageImageAssignment.generated_page_id == page_id,
                    PageImageAssignment.image_metadata_id
                    == restored_record["image_metadata_id"],
                    PageImageAssignment.image_role == record["image_role"],
                )
            restored_assignment = _upsert(
                session,
                PageImageAssignment,
                assignment_statement,
                restored_record,
            )
            page_image_assignment_ids[old_assignment_id] = _required_id(restored_assignment)

        source_authorization_max_versions: dict[int, int] = {}
        for record in data["scoped_media_authorizations"]:
            mapped_requirement_id = _mapped_id(
                planned_page_media_requirement_ids,
                record["media_requirement_id"],
                "scoped_media_authorizations.media_requirement_id",
            )
            source_authorization_max_versions[mapped_requirement_id] = max(
                source_authorization_max_versions.get(mapped_requirement_id, 0),
                record["authorization_version"],
            )
        represented_authorization_requirements = set(
            source_authorization_max_versions
        )
        mapped_website_ids = set(website_ids.values())
        mapped_site_plan_ids = set(site_plan_ids.values())
        mapped_planned_page_ids = set(planned_page_ids.values())
        mapped_generated_page_ids = set(generated_page_ids.values())
        mapped_requirement_ids = set(
            planned_page_media_requirement_ids.values()
        )
        mapped_media_ids = set(image_metadata_ids.values())
        mapped_assignment_ids = set(page_image_assignment_ids.values())
        for target_authorization in session.exec(
            select(ScopedMediaAuthorization)
        ).all():
            touches_restored_scope = (
                target_authorization.website_id in mapped_website_ids
                or target_authorization.site_plan_id in mapped_site_plan_ids
                or target_authorization.planned_page_id in mapped_planned_page_ids
                or (
                    target_authorization.generated_page_id is not None
                    and target_authorization.generated_page_id
                    in mapped_generated_page_ids
                )
                or target_authorization.media_requirement_id
                in mapped_requirement_ids
                or target_authorization.image_metadata_id in mapped_media_ids
                or (
                    target_authorization.page_image_assignment_id is not None
                    and target_authorization.page_image_assignment_id
                    in mapped_assignment_ids
                )
            )
            if (
                touches_restored_scope
                and target_authorization.media_requirement_id
                not in represented_authorization_requirements
            ):
                raise BackupValidationError(
                    "Target scoped-media authorization touches restored scope identities absent from the backup authorization graph; restore was refused."
                )
        for mapped_requirement_id in set(
            planned_page_media_requirement_ids.values()
        ):
            source_max_version = source_authorization_max_versions.get(
                mapped_requirement_id,
                0,
            )
            target_history = list(
                session.exec(
                    select(ScopedMediaAuthorization)
                    .where(
                        ScopedMediaAuthorization.media_requirement_id
                        == mapped_requirement_id
                    )
                    .order_by(ScopedMediaAuthorization.authorization_version)
                ).all()
            )
            _require_restore_compatible_scoped_authorization_prefix(
                target_history,
                source_max_version=source_max_version,
            )

        scoped_media_authorization_ids: dict[int, int] = {}
        scoped_media_authorization_fingerprints: dict[int, str] = {}
        for record in sorted(
            data["scoped_media_authorizations"],
            key=lambda value: (
                value.get("media_requirement_id") or 0,
                value.get("authorization_version") or 0,
            ),
        ):
            old_authorization_id = _record_id(
                record,
                "scoped_media_authorizations",
            )
            requirement_id = _mapped_id(
                planned_page_media_requirement_ids,
                record["media_requirement_id"],
                "scoped_media_authorizations.media_requirement_id",
            )
            restored_record = {
                **record,
                "website_id": _mapped_id(
                    website_ids,
                    record["website_id"],
                    "scoped_media_authorizations.website_id",
                ),
                "site_plan_id": _mapped_id(
                    site_plan_ids,
                    record["site_plan_id"],
                    "scoped_media_authorizations.site_plan_id",
                ),
                "planned_page_id": _mapped_id(
                    planned_page_ids,
                    record["planned_page_id"],
                    "scoped_media_authorizations.planned_page_id",
                ),
                "generated_page_id": _mapped_optional_id(
                    generated_page_ids,
                    record.get("generated_page_id"),
                    "scoped_media_authorizations.generated_page_id",
                ),
                "media_requirement_id": requirement_id,
                "image_metadata_id": _mapped_id(
                    image_metadata_ids,
                    record["image_metadata_id"],
                    "scoped_media_authorizations.image_metadata_id",
                ),
                "page_image_assignment_id": _mapped_optional_id(
                    page_image_assignment_ids,
                    record.get("page_image_assignment_id"),
                    "scoped_media_authorizations.page_image_assignment_id",
                ),
                "supersedes_authorization_id": _mapped_optional_id(
                    scoped_media_authorization_ids,
                    record.get("supersedes_authorization_id"),
                    "scoped_media_authorizations.supersedes_authorization_id",
                ),
                "asset_approved_at": _datetime_value(
                    record["asset_approved_at"],
                    "scoped_media_authorizations.asset_approved_at",
                ),
                "authorized_at": _datetime_value(
                    record["authorized_at"],
                    "scoped_media_authorizations.authorized_at",
                ),
                "authorization_terms": normalize_scoped_media_authorization_terms(
                    record["authorization_terms"]
                ),
            }
            restored_asset = session.get(
                ImageMetadata,
                restored_record["image_metadata_id"],
            )
            if restored_asset is None:
                raise BackupValidationError(
                    "Restored scoped-media authorization asset is missing."
                )
            restored_record["approval_fingerprint"] = (
                scoped_media_approval_fingerprint(
                    {
                        **restored_record,
                        "asset_website_id": restored_asset.website_id,
                        "asset_business_id": restored_asset.business_id,
                        "usage_authorization_mode": (
                            restored_asset.usage_authorization_mode
                        ),
                        "required_authorization_terms": (
                            restored_asset.required_authorization_terms
                        ),
                    }
                )
            )
            restored_record["authorization_fingerprint"] = (
                scoped_media_authorization_fingerprint(restored_record)
            )
            restored_authorization = _restore_scoped_media_authorization(
                session,
                restored_record,
                source_max_version=(
                    source_authorization_max_versions[requirement_id]
                ),
            )
            scoped_media_authorization_ids[old_authorization_id] = _required_id(
                restored_authorization
            )
            scoped_media_authorization_fingerprints[old_authorization_id] = (
                restored_authorization.authorization_fingerprint
            )

        # Page Compositions are created before media assignments so their primary
        # ownership graph can be restored in dependency order. Remap every durable
        # Page Media identity now that the complete governed media graph exists.
        composition_bindings_preserve_source_ids = preserve_source_ids and all(
            source_id == restored_id
            for mapping in (
                website_ids,
                business_ids,
                website_identity_ids,
                site_plan_ids,
                planned_page_ids,
                generated_page_ids,
                service_ids,
                city_ids,
                county_ids,
                navigation_set_ids,
                navigation_item_ids,
                internal_link_intent_ids,
                brand_asset_ids,
                website_media_planning_record_ids,
                planned_page_media_requirement_ids,
                page_image_assignment_ids,
                image_metadata_ids,
                scoped_media_authorization_ids,
                theme_ids,
                website_theme_selection_ids,
                page_composition_ids,
            )
            for source_id, restored_id in mapping.items()
        )
        for record in data.get("page_compositions", []):
            planned_page_id = _mapped_id(
                planned_page_ids,
                record["planned_page_id"],
                "page_compositions.planned_page_id",
            )
            composition = session.exec(
                select(PageComposition).where(
                    PageComposition.planned_page_id == planned_page_id
                )
            ).one()
            if not composition_bindings_preserve_source_ids:
                composition.generated_components = _restore_composition_component_bindings(
                    composition.generated_components,
                    website_ids=website_ids,
                    navigation_set_ids=navigation_set_ids,
                    generated_page_ids=generated_page_ids,
                    planned_page_ids=planned_page_ids,
                    internal_link_intent_ids=internal_link_intent_ids,
                    requirement_ids=planned_page_media_requirement_ids,
                    assignment_ids=page_image_assignment_ids,
                )
                composition.operator_decisions = _restore_composition_component_bindings(
                    composition.operator_decisions,
                    website_ids=website_ids,
                    navigation_set_ids=navigation_set_ids,
                    generated_page_ids=generated_page_ids,
                    planned_page_ids=planned_page_ids,
                    internal_link_intent_ids=internal_link_intent_ids,
                    requirement_ids=planned_page_media_requirement_ids,
                    assignment_ids=page_image_assignment_ids,
                )
                composition.source_snapshot = _restore_composition_source_binding(
                    session,
                    composition.source_snapshot,
                    website_ids=website_ids,
                    business_ids=business_ids,
                    website_identity_ids=website_identity_ids,
                    site_plan_ids=site_plan_ids,
                    planned_page_ids=planned_page_ids,
                    generated_page_ids=generated_page_ids,
                    service_ids=service_ids,
                    city_ids=city_ids,
                    county_ids=county_ids,
                    navigation_set_ids=navigation_set_ids,
                    navigation_item_ids=navigation_item_ids,
                    internal_link_intent_ids=internal_link_intent_ids,
                    brand_asset_ids=brand_asset_ids,
                    planning_record_ids=website_media_planning_record_ids,
                    requirement_ids=planned_page_media_requirement_ids,
                    assignment_ids=page_image_assignment_ids,
                    image_ids=image_metadata_ids,
                    authorization_ids=scoped_media_authorization_ids,
                    authorization_fingerprints=(
                        scoped_media_authorization_fingerprints
                    ),
                )
                composition.source_hash = _canonical_json_hash(
                    composition.source_snapshot
                )
            session.add(composition)

        # Rebuild every composition that the backup claimed was current before
        # restoring durable QA.  A restore can remap navigation, media,
        # identity-asset, and page IDs, so the authoritative restored
        # composition version/hash may differ from the exported identity even
        # though its meaning is unchanged.  QA must bind to that final restored
        # identity, not the intermediate remapped snapshot.
        _refresh_restored_current_compositions(
            session,
            payload=payload,
            site_plan_ids=site_plan_ids,
            page_composition_ids=page_composition_ids,
            preserve_current_identity=preserve_current_composition_identity,
        )
        session.flush()

        source_compositions = {
            record["id"]: record for record in data.get("page_compositions", [])
        }
        generated_page_qa_result_ids: dict[int, int] = {}
        generated_page_qa_result_hashes: dict[str, str] = {}
        pending_qa_supersession: list[
            tuple[dict[str, Any], GeneratedPageQAResult]
        ] = []
        prepared_qa_records: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
        for record in sorted(
            data.get("generated_page_qa_results", []),
            key=lambda value: (str(value.get("created_at") or ""), value["id"]),
        ):
            old_result_id = _record_id(record, "generated_page_qa_results")
            restored_record = _restore_generated_page_qa_result_payload(
                session,
                record,
                website_ids=website_ids,
                site_plan_ids=site_plan_ids,
                planned_page_ids=planned_page_ids,
                generated_page_ids=generated_page_ids,
                generated_page_revision_ids=generated_page_revision_ids,
                page_composition_ids=page_composition_ids,
                source_compositions=source_compositions,
            )
            prepared_qa_records.append((old_result_id, record, restored_record))

        # A restore may target a database that already has newer, divergent QA
        # evidence. Preserve that evidence, but relinquish its `current` claim
        # before upserting the backup's authoritative current row so the
        # one-current-per-page invariant remains atomic and fail closed.
        backup_current_by_page = {
            restored["generated_page_id"]: restored["result_hash"]
            for _, source, restored in prepared_qa_records
            if source.get("lifecycle_status") == "current"
        }
        source_qa_by_id = {
            record["id"]: record
            for record in data.get("generated_page_qa_results", [])
        }
        restored_qa_by_source_id = {
            old_result_id: restored
            for old_result_id, _, restored in prepared_qa_records
        }
        backup_lineage_hashes_by_page: dict[int, list[str]] = {}
        for old_result_id, source, restored in prepared_qa_records:
            if source.get("lifecycle_status") != "current":
                continue
            page_id = restored["generated_page_id"]
            lineage: list[str] = []
            source_result_id: int | None = old_result_id
            source_visited: set[int] = set()
            while source_result_id is not None:
                if source_result_id in source_visited:
                    raise BackupValidationError("Backup QA lineage is cyclic.")
                source_record = source_qa_by_id.get(source_result_id)
                restored_source = restored_qa_by_source_id.get(source_result_id)
                if (
                    source_record is None
                    or restored_source is None
                    or restored_source["generated_page_id"] != page_id
                    or source_record.get("lifecycle_status")
                    == "historical_unbound"
                ):
                    raise BackupValidationError(
                        "Backup QA lineage references a missing, cross-page, or unbound result."
                    )
                source_visited.add(source_result_id)
                lineage.append(restored_source["result_hash"])
                source_result_id = source_record.get("supersedes_qa_result_id")
            backup_lineage_hashes_by_page[page_id] = lineage

        qa_lineage_rebases: list[
            tuple[list[GeneratedPageQAResult], int, str]
        ] = []
        for page_id, backup_result_hash in backup_current_by_page.items():
            target_current = list(
                session.exec(
                    select(GeneratedPageQAResult).where(
                        GeneratedPageQAResult.generated_page_id == page_id,
                        GeneratedPageQAResult.lifecycle_status == "current",
                    )
                ).all()
            )
            if len(target_current) > 1:
                raise BackupValidationError(
                    "Restore target has multiple current QA results for one Generated Page."
                )
            for existing in target_current:
                expected_backup_lineage = backup_lineage_hashes_by_page[page_id]
                backup_hashes = set(expected_backup_lineage)
                observed_backup_lineage: list[str] = []
                target_only_lineage: list[GeneratedPageQAResult] = []
                target_node: GeneratedPageQAResult | None = existing
                target_visited: set[int] = set()
                while target_node is not None:
                    if target_node.id in target_visited:
                        raise BackupValidationError(
                            "Restore target QA lineage is cyclic."
                        )
                    if (
                        target_node.generated_page_id != page_id
                        or target_node.lifecycle_status == "historical_unbound"
                    ):
                        raise BackupValidationError(
                            "Restore target QA lineage is cross-page or unbound."
                        )
                    target_visited.add(target_node.id)
                    if target_node.result_hash in backup_hashes:
                        observed_backup_lineage.append(target_node.result_hash)
                    else:
                        target_only_lineage.append(target_node)
                    parent_id = target_node.supersedes_qa_result_id
                    target_node = (
                        session.get(GeneratedPageQAResult, parent_id)
                        if parent_id is not None
                        else None
                    )
                    if parent_id is not None and target_node is None:
                        raise BackupValidationError(
                            "Restore target QA lineage references a missing result."
                        )

                expected_positions = {
                    result_hash: index
                    for index, result_hash in enumerate(expected_backup_lineage)
                }
                observed_positions = [
                    expected_positions[result_hash]
                    for result_hash in observed_backup_lineage
                ]
                if observed_positions != sorted(set(observed_positions)):
                    raise BackupValidationError(
                        "Restore target QA lineage conflicts with backup ancestry."
                    )
                if (
                    existing.result_hash == backup_result_hash
                    and observed_backup_lineage != expected_backup_lineage
                ):
                    raise BackupValidationError(
                        "Restore target equal-current QA lineage does not contain the backup ancestry exactly."
                    )
                if target_only_lineage:
                    qa_lineage_rebases.append(
                        (target_only_lineage, page_id, backup_result_hash)
                    )
                if existing.result_hash != backup_result_hash:
                    existing.lifecycle_status = "superseded"
                    existing.updated_at = datetime.now(UTC)
                    session.add(existing)
        session.flush()

        for old_result_id, record, restored_record in prepared_qa_records:
            restored_qa_result = _upsert(
                session,
                GeneratedPageQAResult,
                select(GeneratedPageQAResult).where(
                    GeneratedPageQAResult.generated_page_id
                    == restored_record["generated_page_id"],
                    GeneratedPageQAResult.result_hash
                    == restored_record["result_hash"],
                ),
                restored_record,
            )
            generated_page_qa_result_ids[old_result_id] = _required_id(
                restored_qa_result
            )
            generated_page_qa_result_hashes[record["result_hash"]] = (
                restored_record["result_hash"]
            )
            pending_qa_supersession.append((record, restored_qa_result))

        for record, restored_qa_result in pending_qa_supersession:
            page_id = restored_qa_result.generated_page_id
            restored_qa_result.supersedes_qa_result_id = _mapped_optional_id(
                generated_page_qa_result_ids,
                record.get("supersedes_qa_result_id"),
                "generated_page_qa_results.supersedes_qa_result_id",
            )
            session.add(restored_qa_result)

        session.flush()
        for target_only_lineage, page_id, backup_result_hash in qa_lineage_rebases:
            restored_backup_current = session.exec(
                select(GeneratedPageQAResult).where(
                    GeneratedPageQAResult.generated_page_id == page_id,
                    GeneratedPageQAResult.result_hash == backup_result_hash,
                )
            ).one()
            backup_parent_id = restored_backup_current.supersedes_qa_result_id
            for index, target_result in enumerate(target_only_lineage):
                target_result.lifecycle_status = "superseded"
                target_result.supersedes_qa_result_id = (
                    target_only_lineage[index + 1].id
                    if index + 1 < len(target_only_lineage)
                    else backup_parent_id
                )
                session.add(target_result)
            restored_backup_current.supersedes_qa_result_id = (
                target_only_lineage[0].id
            )
            session.add(restored_backup_current)

        for qa_projection, restored_page in pending_generated_page_qa_projections:
            if qa_projection is None:
                restored_page.qa_result = None
                session.add(restored_page)
                continue
            old_qa_result_id = qa_projection.get("qa_result_id")
            if isinstance(old_qa_result_id, int):
                durable = session.get(
                    GeneratedPageQAResult,
                    _mapped_id(
                        generated_page_qa_result_ids,
                        old_qa_result_id,
                        "generated_pages.qa_result.qa_result_id",
                    ),
                )
                if durable is None or durable.lifecycle_status != "current":
                    raise BackupValidationError(
                        "Restored Generated Page QA projection lacks current durable evidence."
                    )
                restored_page.qa_result = _qa_projection_from_durable_result(durable)
                restored_page.qa_status = durable.readiness_status or "not_run"
                restored_page.qa_checked_at = durable.evaluated_at
            else:
                restored_page.qa_result = _restore_qa_page_identity(
                    qa_projection,
                    generated_page_ids=generated_page_ids,
                    website_ids=website_ids,
                    site_plan_ids=site_plan_ids,
                    planned_page_ids=planned_page_ids,
                    generated_page_revision_ids=generated_page_revision_ids,
                    page_composition_ids=page_composition_ids,
                    qa_result_ids=generated_page_qa_result_ids,
                    qa_result_hashes=generated_page_qa_result_hashes,
                    field="generated_pages.qa_result.page_id",
                )
            session.add(restored_page)

        for qa_snapshot, restored_audit in pending_approval_qa_snapshots:
            old_qa_result_id = qa_snapshot.get("qa_result_id")
            if isinstance(old_qa_result_id, int):
                durable = session.get(
                    GeneratedPageQAResult,
                    _mapped_id(
                        generated_page_qa_result_ids,
                        old_qa_result_id,
                        "approval_audits.qa_result_snapshot.qa_result_id",
                    ),
                )
                if durable is None or durable.lifecycle_status == "historical_unbound":
                    raise BackupValidationError(
                        "Restored Approval Audit snapshot lacks bound durable QA evidence."
                    )
                restored_audit.qa_result_snapshot = (
                    _qa_projection_from_durable_result(durable)
                )
                restored_audit.qa_status_at_approval = durable.readiness_status or "not_run"
                restored_audit.qa_checked_at = durable.evaluated_at
            else:
                restored_snapshot = _restore_qa_page_identity(
                    qa_snapshot,
                    generated_page_ids=generated_page_ids,
                    website_ids=website_ids,
                    site_plan_ids=site_plan_ids,
                    planned_page_ids=planned_page_ids,
                    generated_page_revision_ids=generated_page_revision_ids,
                    page_composition_ids=page_composition_ids,
                    qa_result_ids=generated_page_qa_result_ids,
                    qa_result_hashes=generated_page_qa_result_hashes,
                    field="approval_audits.qa_result_snapshot.page_id",
                ) or {}
                if qa_snapshot.get("lifecycle_status") == "candidate":
                    restored_snapshot = _rehash_restored_candidate_qa_projection(
                        session,
                        qa_snapshot,
                        restored_snapshot,
                        source_compositions=source_compositions,
                    )
                restored_audit.qa_result_snapshot = restored_snapshot
            session.add(restored_audit)

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

        for record in data["wordpress_metadata_states"]:
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_metadata_states.generated_page_id"),
                "last_verified_at": _datetime_value(record["last_verified_at"], "wordpress_metadata_states.last_verified_at") if record.get("last_verified_at") else None,
                "last_wordpress_metadata_sync_at": _datetime_value(record["last_wordpress_metadata_sync_at"], "wordpress_metadata_states.last_wordpress_metadata_sync_at") if record.get("last_wordpress_metadata_sync_at") else None,
            }
            _upsert(session, WordPressMetadataState,
                select(WordPressMetadataState).where(WordPressMetadataState.generated_page_id == restored_record["generated_page_id"]), restored_record)

        for record in data["wordpress_metadata_sync_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_metadata_sync_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_metadata_sync_audits.generated_page_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_metadata_sync_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(session, WordPressMetadataSyncAudit,
                select(WordPressMetadataSyncAudit).where(
                    WordPressMetadataSyncAudit.generated_page_id == restored_record["generated_page_id"],
                    WordPressMetadataSyncAudit.attempted_at == attempted_at,
                    WordPressMetadataSyncAudit.payload_hash == record["payload_hash"],
                ), restored_record)

        for record in data["wordpress_deployment_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_deployment_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_deployment_audits.generated_page_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_deployment_audits.completed_at") if record.get("completed_at") else None,
                "shawn_approved_at": _datetime_value(record["shawn_approved_at"], "wordpress_deployment_audits.shawn_approved_at"),
                "backup_completed_at": _datetime_value(record["backup_completed_at"], "wordpress_deployment_audits.backup_completed_at"),
                "backup_deadline": _datetime_value(record["backup_deadline"], "wordpress_deployment_audits.backup_deadline"),
            }
            _upsert(session, WordPressDeploymentAudit,
                select(WordPressDeploymentAudit).where(
                    WordPressDeploymentAudit.generated_page_id == restored_record["generated_page_id"],
                    WordPressDeploymentAudit.attempted_at == attempted_at,
                    WordPressDeploymentAudit.action_type == record["action_type"],
                ), restored_record)

        for record in data["wordpress_heading_correction_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_heading_correction_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_heading_correction_audits.generated_page_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_heading_correction_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(
                session,
                WordPressHeadingCorrectionAudit,
                select(WordPressHeadingCorrectionAudit).where(
                    WordPressHeadingCorrectionAudit.token_fingerprint == record["token_fingerprint"]
                ),
                restored_record,
            )

        deployment_audit_ids = {
            record["id"]: session.exec(
                select(WordPressDeploymentAudit).where(
                    WordPressDeploymentAudit.generated_page_id == _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_deployment_audits.generated_page_id"),
                    WordPressDeploymentAudit.attempted_at == _datetime_value(record["attempted_at"], "wordpress_deployment_audits.attempted_at"),
                    WordPressDeploymentAudit.action_type == record["action_type"],
                )
            ).one().id
            for record in data["wordpress_deployment_audits"]
        }

        for record in data["wordpress_activation_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_activation_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_activation_audits.generated_page_id"),
                "installation_audit_id": _mapped_id(deployment_audit_ids, record["installation_audit_id"], "wordpress_activation_audits.installation_audit_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_activation_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(
                session,
                WordPressActivationAudit,
                select(WordPressActivationAudit).where(
                    WordPressActivationAudit.handle_fingerprint == record["handle_fingerprint"]
                ),
                restored_record,
            )

        activation_audit_ids = {
            record["id"]: session.exec(
                select(WordPressActivationAudit).where(
                    WordPressActivationAudit.handle_fingerprint == record["handle_fingerprint"]
                )
            ).one().id
            for record in data["wordpress_activation_audits"]
        }

        for record in data["wordpress_bootstrap_establishment_audits"]:
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_bootstrap_establishment_audits.generated_page_id"),
                "installation_audit_id": _mapped_id(deployment_audit_ids, record["installation_audit_id"], "wordpress_bootstrap_establishment_audits.installation_audit_id"),
                "activation_audit_id": _mapped_id(activation_audit_ids, record["activation_audit_id"], "wordpress_bootstrap_establishment_audits.activation_audit_id"),
                "attempted_at": _datetime_value(record["attempted_at"], "wordpress_bootstrap_establishment_audits.attempted_at"),
                "completed_at": _datetime_value(record["completed_at"], "wordpress_bootstrap_establishment_audits.completed_at") if record.get("completed_at") else None,
                "reconciled_at": _datetime_value(record["reconciled_at"], "wordpress_bootstrap_establishment_audits.reconciled_at") if record.get("reconciled_at") else None,
            }
            _upsert(
                session,
                WordPressBootstrapEstablishmentAudit,
                select(WordPressBootstrapEstablishmentAudit).where(
                    WordPressBootstrapEstablishmentAudit.manual_handle_fingerprint == record["manual_handle_fingerprint"]
                ),
                restored_record,
            )

        for record in data["wordpress_plugin_upgrade_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_plugin_upgrade_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_plugin_upgrade_audits.generated_page_id"),
                "installation_audit_id": _mapped_id(deployment_audit_ids, record["installation_audit_id"], "wordpress_plugin_upgrade_audits.installation_audit_id"),
                "activation_audit_id": _mapped_id(activation_audit_ids, record["activation_audit_id"], "wordpress_plugin_upgrade_audits.activation_audit_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_plugin_upgrade_audits.completed_at") if record.get("completed_at") else None,
                "reconciled_at": _datetime_value(record["reconciled_at"], "wordpress_plugin_upgrade_audits.reconciled_at") if record.get("reconciled_at") else None,
            }
            _upsert(
                session,
                WordPressPluginUpgradeAudit,
                select(WordPressPluginUpgradeAudit).where(
                    WordPressPluginUpgradeAudit.handle_fingerprint == record["handle_fingerprint"]
                ),
                restored_record,
            )

        upgrade_audit_ids = {
            record["id"]: session.exec(
                select(WordPressPluginUpgradeAudit).where(
                    WordPressPluginUpgradeAudit.handle_fingerprint == record["handle_fingerprint"]
                )
            ).one().id
            for record in data["wordpress_plugin_upgrade_audits"]
        }

        for record in data["wordpress_bootstrap_cleanup_audits"]:
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_bootstrap_cleanup_audits.generated_page_id"),
                "installation_audit_id": _mapped_id(deployment_audit_ids, record["installation_audit_id"], "wordpress_bootstrap_cleanup_audits.installation_audit_id"),
                "activation_audit_id": _mapped_id(activation_audit_ids, record["activation_audit_id"], "wordpress_bootstrap_cleanup_audits.activation_audit_id"),
                "upgrade_audit_id": _mapped_id(upgrade_audit_ids, record["upgrade_audit_id"], "wordpress_bootstrap_cleanup_audits.upgrade_audit_id"),
                "attempted_at": _datetime_value(record["attempted_at"], "wordpress_bootstrap_cleanup_audits.attempted_at"),
                "deactivated_at": _datetime_value(record["deactivated_at"], "wordpress_bootstrap_cleanup_audits.deactivated_at") if record.get("deactivated_at") else None,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_bootstrap_cleanup_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(
                session,
                WordPressBootstrapCleanupAudit,
                select(WordPressBootstrapCleanupAudit).where(
                    WordPressBootstrapCleanupAudit.deactivation_handle_fingerprint
                    == record["deactivation_handle_fingerprint"]
                ),
                restored_record,
            )

        for record in data["wordpress_metadata_lifecycle_audits"]:
            attempted_at = _datetime_value(record["attempted_at"], "wordpress_metadata_lifecycle_audits.attempted_at")
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(generated_page_ids, record["generated_page_id"], "wordpress_metadata_lifecycle_audits.generated_page_id"),
                "installation_audit_id": _mapped_id(deployment_audit_ids, record["installation_audit_id"], "wordpress_metadata_lifecycle_audits.installation_audit_id"),
                "activation_audit_id": _mapped_id(activation_audit_ids, record["activation_audit_id"], "wordpress_metadata_lifecycle_audits.activation_audit_id"),
                "attempted_at": attempted_at,
                "completed_at": _datetime_value(record["completed_at"], "wordpress_metadata_lifecycle_audits.completed_at") if record.get("completed_at") else None,
            }
            _upsert(
                session,
                WordPressMetadataLifecycleAudit,
                select(WordPressMetadataLifecycleAudit).where(
                    WordPressMetadataLifecycleAudit.handle_fingerprint == record["handle_fingerprint"]
                ),
                restored_record,
            )

        metadata_lifecycle_audit_ids = {
            record["id"]: session.exec(
                select(WordPressMetadataLifecycleAudit).where(
                    WordPressMetadataLifecycleAudit.handle_fingerprint
                    == record["handle_fingerprint"]
                )
            ).one().id
            for record in data["wordpress_metadata_lifecycle_audits"]
        }

        for record in data["wordpress_cache_aware_rendering_audits"]:
            attempted_at = _datetime_value(
                record["attempted_at"],
                "wordpress_cache_aware_rendering_audits.attempted_at",
            )
            restored_record = {
                **record,
                "generated_page_id": _mapped_id(
                    generated_page_ids,
                    record["generated_page_id"],
                    "wordpress_cache_aware_rendering_audits.generated_page_id",
                ),
                "staging_audit_id": _mapped_id(
                    metadata_lifecycle_audit_ids,
                    record["staging_audit_id"],
                    "wordpress_cache_aware_rendering_audits.staging_audit_id",
                ),
                "recovery_disable_audit_id": _mapped_id(
                    metadata_lifecycle_audit_ids,
                    record["recovery_disable_audit_id"],
                    "wordpress_cache_aware_rendering_audits.recovery_disable_audit_id",
                ),
                "attempted_at": attempted_at,
                "completed_at": (
                    _datetime_value(
                        record["completed_at"],
                        "wordpress_cache_aware_rendering_audits.completed_at",
                    )
                    if record.get("completed_at")
                    else None
                ),
            }
            _upsert(
                session,
                WordPressCacheAwareRenderingAudit,
                select(WordPressCacheAwareRenderingAudit).where(
                    WordPressCacheAwareRenderingAudit.rendering_handle_fingerprint
                    == record["rendering_handle_fingerprint"]
                ),
                restored_record,
            )

        for record in data["wordpress_deployment_nonces"]:
            restored_record = {
                **record,
                "audit_id": _mapped_id(deployment_audit_ids, record["audit_id"], "wordpress_deployment_nonces.audit_id") if record.get("audit_id") is not None else None,
                "consumed_at": _datetime_value(record["consumed_at"], "wordpress_deployment_nonces.consumed_at"),
            }
            _upsert(session, WordPressDeploymentNonce,
                select(WordPressDeploymentNonce).where(WordPressDeploymentNonce.jti == record["jti"]), restored_record)

        for record in data["wordpress_deployment_transitions"]:
            restored_record = {
                **record,
                "audit_id": _mapped_id(deployment_audit_ids, record["audit_id"], "wordpress_deployment_transitions.audit_id"),
                "transitioned_at": _datetime_value(record["transitioned_at"], "wordpress_deployment_transitions.transitioned_at"),
            }
            _upsert(session, WordPressDeploymentTransition,
                select(WordPressDeploymentTransition).where(WordPressDeploymentTransition.request_identifier == record["request_identifier"]), restored_record)

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

        # Re-check at the transaction boundary after every remaining record has
        # been restored.  This is normally an unchanged no-op; retaining the
        # check makes future composition dependencies fail closed.
        _refresh_restored_current_compositions(
            session,
            payload=payload,
            site_plan_ids=site_plan_ids,
            page_composition_ids=page_composition_ids,
            preserve_current_identity=preserve_current_composition_identity,
        )

        if preserve_source_ids:
            _synchronize_postgresql_restore_sequences(session)
        session.commit()
    except Exception as exc:
        session.rollback()
        if isinstance(exc, BackupValidationError):
            raise
        raise BackupValidationError(f"Restore failed and was rolled back: {exc}") from exc
    finally:
        session.info.pop(_RESTORE_PRESERVE_SOURCE_IDS, None)
        session.info.pop(_RESTORE_EXPLICIT_ID_MODELS, None)

    return {
        "file_name": backup_path.name,
        "status": "restored",
        "records_processed": sum(payload["metadata"]["table_counts"].values()),
        "table_counts": payload["metadata"]["table_counts"],
    }


def _refresh_restored_current_compositions(
    session: Session,
    *,
    payload: dict[str, Any],
    site_plan_ids: dict[int, int],
    page_composition_ids: dict[int, int],
    preserve_current_identity: bool,
) -> None:
    """Materialize the authoritative remapped composition graph during restore."""

    data = payload["data"]
    if not data.get("page_compositions"):
        return

    if preserve_current_identity:
        preserve_current_identity = (
            _restored_current_compositions_match_authoritative_sources(
                session,
                data=data,
                site_plan_ids=site_plan_ids,
                page_composition_ids=page_composition_ids,
            )
        )

    # An exact identity-preserving restore already carries the authoritative
    # current composition graph.  Rebuilding it would manufacture a new
    # version/hash (and therefore new QA identity) even though every bound ID
    # and governed payload is unchanged.  Remapped or divergent restores still
    # take the full refresh path below.
    exact_current_identity = True
    for source in data["page_compositions"]:
        if source.get("status") != "current":
            exact_current_identity = False
            break
        source_id = _record_id(source, "page_compositions")
        restored_id = page_composition_ids.get(source_id)
        restored = session.get(PageComposition, restored_id) if restored_id else None
        if (
            restored_id != source_id
            or restored is None
            or restored.website_id != source.get("website_id")
            or restored.site_plan_id != source.get("site_plan_id")
            or restored.planned_page_id != source.get("planned_page_id")
            or restored.generated_page_id != source.get("generated_page_id")
            or restored.composition_version != source.get("composition_version")
            or restored.status != source.get("status")
            or restored.source_snapshot != source.get("source_snapshot")
            or restored.source_hash != source.get("source_hash")
            or restored.generated_components != source.get("generated_components")
            or restored.operator_decisions != source.get("operator_decisions")
        ):
            exact_current_identity = False
            break
    if preserve_current_identity and exact_current_identity:
        return

    from app.services.page_composition import refresh_site_plan_compositions
    from app.services.site_connections import read_site_connection_plan

    composition_plan_ids = {
        _mapped_id(
            site_plan_ids,
            record["site_plan_id"],
            "page_compositions.site_plan_id",
        )
        for record in data["page_compositions"]
    }
    for restored_plan_id in sorted(composition_plan_ids):
        old_plan_ids = {
            old_id
            for old_id, new_id in site_plan_ids.items()
            if new_id == restored_plan_id
        }
        backed_compositions = [
            record
            for record in data["page_compositions"]
            if record.get("site_plan_id") in old_plan_ids
        ]
        graph_ready = (
            payload["metadata"]["version"]
            in {"0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}
            and read_site_connection_plan(session, restored_plan_id).ready
        )
        claims_current = bool(backed_compositions) and all(
            record.get("status") == "current"
            for record in backed_compositions
        )
        if graph_ready and claims_current:
            result = refresh_site_plan_compositions(
                session,
                restored_plan_id,
                commit=False,
            )
            expected_count = len(
                session.exec(
                    select(PlannedPage).where(
                        PlannedPage.site_plan_id == restored_plan_id,
                        PlannedPage.generated_page_id.is_not(None),
                    )
                ).all()
            )
            observed_count = result.created + result.refreshed + result.unchanged
            if (
                result.blocked
                or observed_count != expected_count
                or len(result.compositions) != expected_count
            ):
                raise BackupValidationError(
                    "Authoritative Site Connection restore could not refresh every expected composition."
                )
        else:
            for composition in session.exec(
                select(PageComposition).where(
                    PageComposition.site_plan_id == restored_plan_id
                )
            ).all():
                composition.status = "stale"
                composition.updated_at = datetime.now(UTC)
                session.add(composition)


def _restored_current_compositions_match_authoritative_sources(
    session: Session,
    *,
    data: dict[str, list[dict[str, Any]]],
    site_plan_ids: dict[int, int],
    page_composition_ids: dict[int, int],
) -> bool:
    """Prove a Backup 0.57+ current graph can retain its exact identity.

    The shortcut is deliberately based on the same live source projection and
    Site Connection readiness contract used by composition refresh.  A backup
    that is internally self-consistent but stale, incomplete, or missing a
    dependency therefore takes the authoritative refresh path instead.
    """

    source_compositions = data.get("page_compositions", [])
    if not source_compositions or any(
        record.get("status") != "current" for record in source_compositions
    ):
        return False

    expected_composition_bindings = sorted(
        (
            record["site_plan_id"],
            record["id"],
            record["generated_page_id"],
        )
        for record in data.get("planned_pages", [])
        if type(record.get("site_plan_id")) is int
        and type(record.get("id")) is int
        and type(record.get("generated_page_id")) is int
    )
    backed_composition_bindings = sorted(
        (
            record["site_plan_id"],
            record["planned_page_id"],
            record["generated_page_id"],
        )
        for record in source_compositions
    )
    if backed_composition_bindings != expected_composition_bindings:
        return False

    from app.services.page_composition import (
        PageCompositionError,
        _authoritative_projection,
        _validate,
    )
    from app.services.site_connections import (
        SiteConnectionError,
        read_site_connection_plan,
    )

    source_plan_ids = sorted({record["site_plan_id"] for record in source_compositions})
    for source_plan_id in source_plan_ids:
        restored_plan_id = site_plan_ids.get(source_plan_id)
        if restored_plan_id != source_plan_id:
            return False
        try:
            if not read_site_connection_plan(session, restored_plan_id).ready:
                return False
        except SiteConnectionError:
            return False

        expected_plan_bindings = [
            binding
            for binding in expected_composition_bindings
            if binding[0] == source_plan_id
        ]
        restored_plan_bindings = sorted(
            (
                composition.site_plan_id,
                composition.planned_page_id,
                composition.generated_page_id,
            )
            for composition in session.exec(
                select(PageComposition).where(
                    PageComposition.site_plan_id == restored_plan_id
                )
            ).all()
        )
        if restored_plan_bindings != expected_plan_bindings:
            return False

    for source in source_compositions:
        source_id = _record_id(source, "page_compositions")
        restored_id = page_composition_ids.get(source_id)
        restored = session.get(PageComposition, restored_id) if restored_id else None
        if restored_id != source_id or restored is None:
            return False
        plan = session.get(SitePlan, source["site_plan_id"])
        planned = session.get(PlannedPage, source["planned_page_id"])
        generated = session.get(GeneratedPage, source["generated_page_id"])
        if (
            plan is None
            or planned is None
            or generated is None
            or planned.site_plan_id != plan.id
            or planned.generated_page_id != generated.id
        ):
            return False
        try:
            authoritative_snapshot, authoritative_components = _authoritative_projection(
                session,
                plan,
                planned,
                generated,
                operator_decisions=source.get("operator_decisions", []),
            )
            _validate(
                session,
                restored,
                plan,
                planned,
                generated,
            )
        except PageCompositionError:
            return False
        if (
            authoritative_snapshot != source.get("source_snapshot")
            or _canonical_json_hash(authoritative_snapshot)
            != source.get("source_hash")
            or authoritative_components != source.get("generated_components")
        ):
            return False
    return True


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
    if backup_version != "0.30":
        for group in ("wordpress_metadata_states", "wordpress_metadata_sync_audits"):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if "wordpress_deployment_audits" not in data:
        data["wordpress_deployment_audits"] = []
        counts["wordpress_deployment_audits"] = 0
    for group in ("wordpress_deployment_nonces", "wordpress_deployment_transitions"):
        if group not in data:
            data[group] = []
            counts[group] = 0
    if "wordpress_heading_correction_audits" not in data:
        data["wordpress_heading_correction_audits"] = []
        counts["wordpress_heading_correction_audits"] = 0
    if "wordpress_activation_audits" not in data:
        data["wordpress_activation_audits"] = []
        counts["wordpress_activation_audits"] = 0
    if "wordpress_plugin_upgrade_audits" not in data:
        data["wordpress_plugin_upgrade_audits"] = []
        counts["wordpress_plugin_upgrade_audits"] = 0
    if "wordpress_bootstrap_cleanup_audits" not in data:
        data["wordpress_bootstrap_cleanup_audits"] = []
        counts["wordpress_bootstrap_cleanup_audits"] = 0
    if "wordpress_bootstrap_establishment_audits" not in data:
        data["wordpress_bootstrap_establishment_audits"] = []
        counts["wordpress_bootstrap_establishment_audits"] = 0
    if "wordpress_metadata_lifecycle_audits" not in data:
        data["wordpress_metadata_lifecycle_audits"] = []
        counts["wordpress_metadata_lifecycle_audits"] = 0
    if "wordpress_cache_aware_rendering_audits" not in data:
        data["wordpress_cache_aware_rendering_audits"] = []
        counts["wordpress_cache_aware_rendering_audits"] = 0
    if backup_version != "0.42" and backup_version != "0.43":
        for group in ("brands", "websites", "website_identities"):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.43", "0.44", "0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in ("site_plans", "planned_pages", "planning_records"):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.44", "0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "site_connection_planning_records",
            "navigation_sets",
            "navigation_items",
            "internal_link_intents",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "website_coverage_planning_records",
            "website_service_coverage_decisions",
            "website_county_coverage_decisions",
            "website_city_coverage_decisions",
            "website_service_city_coverage_decisions",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "drafting_eligibility_assessments",
            "drafting_eligibility_dispositions",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.47", "0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "supporting_page_authorizations",
            "pre_draft_distinctness_briefs",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.48", "0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "website_draft_generation_runs",
            "website_draft_generation_items",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if "website_service_county_coverage_decisions" not in data:
        data.setdefault("website_service_county_coverage_decisions", [])
        counts.setdefault("website_service_county_coverage_decisions", 0)
    if backup_version not in {"0.49", "0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in ("semantic_component_definitions", "page_compositions"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.50", "0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in ("brand_assets", "website_identity_asset_assignments"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.51", "0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in ("themes", "website_theme_selections"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        for group in (
            "website_media_planning_records",
            "planned_page_media_requirements",
        ):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.55", "0.56", "0.57", "0.58"}:
        data.setdefault("generated_page_qa_results", [])
        counts.setdefault("generated_page_qa_results", 0)
    if backup_version not in {"0.56", "0.57", "0.58"}:
        data.setdefault("scoped_media_authorizations", [])
        counts.setdefault("scoped_media_authorizations", 0)
        for record in data.get("image_metadata", []):
            if isinstance(record, dict):
                record.setdefault("usage_authorization_mode", "contract_default")
                record.setdefault("required_authorization_terms", [])
    if backup_version not in {"0.57", "0.58"}:
        for group in (
            "theme_families",
            "theme_family_versions",
            "website_theme_configurations",
            "website_theme_component_configurations",
            "theme_configuration_audits",
        ):
            records = data.setdefault(group, [])
            if records:
                raise BackupValidationError(
                    f"Legacy backup version cannot contain '{group}' records."
                )
            counts.setdefault(group, 0)
    if backup_version != "0.58":
        for group in FORM_DELIVERY_BACKUP_GROUPS:
            records = data.setdefault(group, [])
            if records:
                raise BackupValidationError(
                    f"Legacy backup version cannot contain '{group}' records."
                )
            counts.setdefault(group, 0)

    for group in BACKUP_MODELS:
        records = data.get(group)
        if not isinstance(records, list):
            raise BackupValidationError(f"Backup data group '{group}' must be a list.")
        if counts.get(group) != len(records):
            raise BackupValidationError(f"Backup count mismatch for '{group}'.")
        if not all(isinstance(record, dict) for record in records):
            raise BackupValidationError(f"Backup data group '{group}' contains an invalid record.")

    _canonicalize_navigation_decision_timestamps(data)
    _canonicalize_form_delivery_utc_timestamps(data)

    valid_asset_statuses = {"draft", "pending_review", "approved", "rejected", "retired"}
    valid_asset_types = {
        "primary_logo", "alternate_logo", "brand_mark", "favicon",
        "browser_icon", "apple_touch_icon", "open_graph_image",
    }
    valid_usages = {
        "website_header", "website_footer", "browser_tab", "social_preview",
        "reports", "login_screen",
    }
    valid_provenance_types = {
        "company_original", "commissioned", "licensed", "public_domain",
    }
    valid_rights_statuses = {"owned", "licensed", "commissioned", "public_domain"}
    media_settings = get_settings()
    for record in data["brand_assets"]:
        approved_usage = record.get("approved_usage")
        restrictions = record.get("restrictions")
        checksum = record.get("checksum_sha256")
        original_filename = record.get("original_filename")
        stored_filename = record.get("stored_filename")
        mime_type = record.get("mime_type")
        if (
            record.get("status") not in valid_asset_statuses
            or record.get("asset_type") not in valid_asset_types
            or not isinstance(record.get("asset_key"), str)
            or BRAND_ASSET_KEY_PATTERN.fullmatch(record["asset_key"]) is None
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or not isinstance(approved_usage, list)
            or not approved_usage
            or not _is_normalized_string_list(approved_usage)
            or not set(approved_usage) <= valid_usages
            or not isinstance(restrictions, list)
            or not restrictions
            or not _is_normalized_string_list(restrictions)
            or not set(restrictions) <= valid_usages
            or set(approved_usage) & set(restrictions)
            or not str(record.get("purpose") or "").strip()
            or not str(record.get("accessibility_description") or "").strip()
            or not str(record.get("created_by") or "").strip()
            or record.get("provenance_type") not in valid_provenance_types
            or not str(record.get("provenance_notes") or "").strip()
            or record.get("rights_status") not in valid_rights_statuses
            or not str(record.get("rights_holder") or "").strip()
            or not str(record.get("rights_notes") or "").strip()
            or not _is_safe_backup_filename(original_filename)
            or not _is_safe_backup_filename(stored_filename)
            or mime_type not in BRAND_ASSET_MIME_EXTENSIONS
            or Path(original_filename).suffix.lower() not in BRAND_ASSET_MIME_EXTENSIONS.get(mime_type, set())
            or Path(stored_filename).suffix.lower() not in BRAND_ASSET_MIME_EXTENSIONS.get(mime_type, set())
            or not _is_positive_int(record.get("file_size"))
            or record["file_size"] > media_settings.media_max_upload_bytes
            or not _is_positive_int(record.get("width"))
            or not _is_positive_int(record.get("height"))
            or record["width"] * record["height"] > media_settings.media_max_pixels
            or not _has_coherent_managed_asset_urls(
                record,
                stored_filename,
                str(media_settings.media_public_url),
            )
            or not isinstance(checksum, str)
            or len(checksum) != 64
            or any(character not in "0123456789abcdef" for character in checksum)
        ):
            raise BackupValidationError("Backup contains an invalid governed Brand Asset.")
        if record["status"] == "approved":
            if not str(record.get("approved_by") or "").strip() or record.get("approved_at") is None:
                raise BackupValidationError(
                    "Backup contains an approved Brand Asset without approval provenance."
                )
            _datetime_value(record["approved_at"], "brand_assets.approved_at")
        if record["status"] == "retired":
            if (
                not str(record.get("retired_by") or "").strip()
                or not str(record.get("retirement_rationale") or "").strip()
                or record.get("retired_at") is None
            ):
                raise BackupValidationError(
                    "Backup contains a retired Brand Asset without retirement provenance."
                )
            _datetime_value(record["retired_at"], "brand_assets.retired_at")
    valid_assignment_statuses = {"active", "replaced", "retired"}
    valid_slots = {
        "header_logo", "footer_logo", "favicon", "browser_icon",
        "apple_touch_icon", "open_graph_image",
    }
    active_slot_keys: set[tuple[int, str]] = set()
    for record in data["website_identity_asset_assignments"]:
        if (
            record.get("status") not in valid_assignment_statuses
            or record.get("slot") not in valid_slots
            or not str(record.get("assigned_by") or "").strip()
            or not str(record.get("rationale") or "").strip()
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or record.get("assigned_at") is None
        ):
            raise BackupValidationError("Backup contains an invalid Website Identity asset selection.")
        assigned_at = _datetime_value(
            record["assigned_at"],
            "website_identity_asset_assignments.assigned_at",
        )
        replaced_at = record.get("replaced_at")
        if record["status"] == "active" and replaced_at is not None:
            raise BackupValidationError(
                "Backup contains an active Website Identity asset selection with replacement provenance."
            )
        if record["status"] == "replaced" and replaced_at is None:
            raise BackupValidationError(
                "Backup contains a replaced Website Identity asset selection without replacement provenance."
            )
        if replaced_at is not None:
            replacement_time = _datetime_value(
                replaced_at,
                "website_identity_asset_assignments.replaced_at",
            )
            if _comparable_datetime(replacement_time) < _comparable_datetime(assigned_at):
                raise BackupValidationError(
                    "Backup contains Website Identity replacement provenance before its assignment."
                )
        if record["status"] == "active":
            key = (record["website_identity_id"], record["slot"])
            if key in active_slot_keys:
                raise BackupValidationError("Backup contains multiple active selections for one Website Identity slot.")
            active_slot_keys.add(key)

    valid_theme_lifecycle_statuses = {"draft", "available", "retired"}
    valid_theme_approval_statuses = {"pending_review", "approved", "rejected"}
    from app.schemas.themes import ThemeDesignTokens

    for record in data["themes"]:
        tokens = record.get("design_tokens")
        token_hash = record.get("token_hash_sha256")
        if (
            record.get("lifecycle_status") not in valid_theme_lifecycle_statuses
            or record.get("approval_status") not in valid_theme_approval_statuses
            or not str(record.get("theme_key") or "").strip()
            or not str(record.get("theme_name") or "").strip()
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or not isinstance(record.get("token_contract_version"), int)
            or record["token_contract_version"] < 1
            or not isinstance(tokens, dict)
            or not tokens
            or not isinstance(token_hash, str)
            or len(token_hash) != 64
            or any(character not in "0123456789abcdef" for character in token_hash)
            or token_hash != _canonical_json_hash(tokens)
            or not str(record.get("created_by") or "").strip()
            or not str(record.get("provenance_type") or "").strip()
            or not str(record.get("provenance_notes") or "").strip()
        ):
            raise BackupValidationError("Backup contains an invalid governed Theme.")
        try:
            ThemeDesignTokens.model_validate(tokens)
        except ValueError as exc:
            raise BackupValidationError(
                "Backup contains a Theme with an invalid design-token contract."
            ) from exc
        if record["approval_status"] == "approved":
            if (
                not str(record.get("approved_by") or "").strip()
                or record.get("approved_at") is None
            ):
                raise BackupValidationError(
                    "Backup contains an approved Theme without approval provenance."
                )
            _datetime_value(record["approved_at"], "themes.approved_at")
        if record["lifecycle_status"] == "retired":
            if (
                not str(record.get("retired_by") or "").strip()
                or not str(record.get("retirement_rationale") or "").strip()
                or record.get("retired_at") is None
            ):
                raise BackupValidationError(
                    "Backup contains a retired Theme without retirement provenance."
                )
            _datetime_value(record["retired_at"], "themes.retired_at")

    valid_theme_selection_statuses = {"active", "replaced", "retired"}
    active_theme_websites: set[int] = set()
    for record in data["website_theme_selections"]:
        if (
            record.get("status") not in valid_theme_selection_statuses
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or not str(record.get("selected_by") or "").strip()
            or not str(record.get("rationale") or "").strip()
            or record.get("selected_at") is None
        ):
            raise BackupValidationError(
                "Backup contains an invalid Website Theme selection."
            )
        selected_at = _datetime_value(
            record["selected_at"], "website_theme_selections.selected_at"
        )
        replaced_at = record.get("replaced_at")
        if record["status"] == "active" and replaced_at is not None:
            raise BackupValidationError(
                "Backup contains an active Website Theme selection with replacement provenance."
            )
        if record["status"] == "replaced" and replaced_at is None:
            raise BackupValidationError(
                "Backup contains a replaced Website Theme selection without replacement provenance."
            )
        if replaced_at is not None and _comparable_datetime(
            _datetime_value(
                replaced_at, "website_theme_selections.replaced_at"
            )
        ) < _comparable_datetime(selected_at):
            raise BackupValidationError(
                "Backup contains Website Theme replacement provenance before selection."
            )
        if record["status"] == "active":
            website_id = record["website_id"]
            if website_id in active_theme_websites:
                raise BackupValidationError(
                    "Backup contains multiple active Theme selections for one Website."
                )
            active_theme_websites.add(website_id)

    for group in (
        "website_service_coverage_decisions",
        "website_county_coverage_decisions",
        "website_city_coverage_decisions",
        "website_service_city_coverage_decisions",
        "website_service_county_coverage_decisions",
    ):
        for record in data[group]:
            if record.get("status") not in {"included", "excluded", "deferred"}:
                raise BackupValidationError(
                    f"Backup contains an invalid coverage status in '{group}'."
                )
            if (
                not isinstance(record.get("decision_version"), int)
                or record["decision_version"] < 1
                or not str(record.get("decided_by") or "").strip()
            ):
                raise BackupValidationError(
                    f"Backup contains invalid coverage provenance in '{group}'."
                )

    valid_run_statuses = {
        "preparing",
        "running",
        "interrupted",
        "completed",
        "completed_with_errors",
    }
    for record in data["website_draft_generation_runs"]:
        if record.get("status") not in valid_run_statuses:
            raise BackupValidationError(
                "Backup contains an invalid Website draft-generation run status."
            )
        if not str(record.get("manifest_hash") or "").strip():
            raise BackupValidationError(
                "Backup contains a draft-generation run without a manifest identity."
            )
    valid_item_outcomes = {
        "pending",
        "generated",
        "already_drafted",
        "blocked",
        "deferred",
        "excluded",
        "stale",
        "consolidation_recommended",
        "unsupported",
        "error",
    }
    for record in data["website_draft_generation_items"]:
        if record.get("outcome") not in valid_item_outcomes:
            raise BackupValidationError(
                "Backup contains an invalid Website draft-generation item outcome."
            )

    _validate_site_connection_decision_provenance(data, backup_version)
    _validate_nested_qa_page_identities(data, backup_version)
    _validate_theme_configuration_graph(data, backup_version)
    _validate_form_delivery_graph(data, backup_version)
    _validate_unique_records(data)
    _validate_backup_references(data)
    _validate_brand_asset_ownership(data)
    _validate_theme_ownership(data)
    _validate_page_media_ownership(data, backup_version)
    _validate_scoped_media_authorizations(data, backup_version)
    _validate_generated_page_qa_results(data, backup_version)
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


def _reserve_backup_path(destination: Path, timestamp: datetime) -> Path:
    """Atomically reserve one final backup filename for this export.

    The empty placeholder exists only between successful validation and the
    same-filesystem atomic replacement. Exclusive creation prevents concurrent
    exports from selecting or overwriting the same final filename.
    """

    candidate_time = timestamp
    while True:
        candidate = destination / f"atlas-backup-{candidate_time.strftime('%Y-%m-%d-%H%M%S')}.json"
        try:
            with candidate.open("x", encoding="utf-8"):
                pass
            return candidate
        except FileExistsError:
            pass
        candidate_time += timedelta(seconds=1)


def _restore_managed_tables_are_empty(
    session: Session,
    data: dict[str, list[dict[str, Any]]],
) -> bool:
    """Prove the target is empty apart from exact migration-owned seed rows."""

    available_tables = set(sa_inspect(session.connection()).get_table_names())
    checked_tables: set[str] = set()
    for group, model in BACKUP_MODELS.items():
        table_key = model.__table__.key
        if table_key in checked_tables:
            continue
        checked_tables.add(table_key)
        if table_key not in available_tables:
            if data.get(group):
                raise BackupValidationError(
                    f"Target schema does not contain table '{table_key}' required by '{group}'."
                )
            continue
        if session.exec(select(model).limit(1)).first() is None:
            continue
        if group != "semantic_component_definitions":
            return False

        # Migration 0037 deliberately seeds the canonical semantic component
        # registry on an otherwise clean migrated database.  Treat those rows
        # as clean-target infrastructure only when their durable identity and
        # complete contract payload exactly match the accepted backup; seed
        # timestamps are intentionally excluded because each clean migration
        # run assigns its own creation instant.
        fields = (
            "id",
            "component_key",
            "contract_version",
            "purpose",
            "required_inputs",
            "customer_outcome",
            "compatible_page_types",
            "supported_variants",
            "accessibility_requirements",
            "status",
        )
        observed = {
            (record.component_key, record.contract_version): {
                field: (
                    tuple(value) if isinstance(value, list) else value
                )
                for field in fields
                for value in (getattr(record, field),)
            }
            for record in session.exec(select(SemanticComponentDefinition)).all()
        }
        expected = {
            (record["component_key"], record["contract_version"]): {
                field: (
                    tuple(record[field])
                    if isinstance(record[field], list)
                    else record[field]
                )
                for field in fields
            }
            for record in data.get(group, [])
        }
        if observed.keys() != expected.keys():
            return False
        for identity, observed_contract in observed.items():
            expected_contract = expected[identity]
            if (
                identity == ("related_page_links", 1)
                and observed_contract["purpose"]
                == "Present approved contextual page relationships."
                and expected_contract["purpose"]
                == "Present operator-approved contextual page relationships."
            ):
                observed_contract = {
                    **observed_contract,
                    "purpose": expected_contract["purpose"],
                }
            if observed_contract != expected_contract:
                return False
    return True


def _restore_managed_tables_match_backup(
    session: Session,
    data: dict[str, list[dict[str, Any]]],
) -> bool:
    """Return true only when the complete managed target exactly matches data."""

    available_tables = set(sa_inspect(session.connection()).get_table_names())
    observed: dict[str, list[dict[str, Any]]] = {}
    for group, model in BACKUP_MODELS.items():
        table_key = model.__table__.key
        if table_key not in available_tables:
            if data.get(group):
                return False
            observed[group] = []
            continue
        records = session.exec(select(model).order_by(model.id)).all()
        if group == "settings":
            records = [
                record
                for record in records
                if not is_sensitive_setting_key(record.setting_key)
            ]
        observed[group] = [record.model_dump(mode="json") for record in records]
    expected = deepcopy(data)
    for comparable in (observed, expected):
        _canonicalize_navigation_decision_timestamps(comparable)
        _canonicalize_converged_utc_timestamps(comparable)
        _canonicalize_form_delivery_utc_timestamps(comparable)
    return observed == expected


def _restore_insert_values(
    session: Session,
    model: type[SQLModel],
    normalized: SQLModel,
) -> dict[str, Any]:
    values = normalized.model_dump(exclude={"id"})
    if not session.info.get(_RESTORE_PRESERVE_SOURCE_IDS):
        return values

    source_id = getattr(normalized, "id", None)
    if isinstance(source_id, bool) or not isinstance(source_id, int):
        raise BackupValidationError(
            f"Clean-target restore requires an integer source id for {model.__name__}."
        )
    if session.get(model, source_id) is not None:
        raise BackupValidationError(
            f"Clean-target restore found a duplicate source id for {model.__name__}."
        )
    values["id"] = source_id
    explicit_models = session.info.get(_RESTORE_EXPLICIT_ID_MODELS)
    if not isinstance(explicit_models, set):
        raise BackupValidationError(
            "Clean-target restore identity tracking is unavailable."
        )
    explicit_models.add(model)
    return values


def _synchronize_postgresql_restore_sequences(session: Session) -> None:
    """Advance PostgreSQL sequences after a clean restore inserted source ids."""

    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    explicit_models = session.info.get(_RESTORE_EXPLICIT_ID_MODELS)
    if not isinstance(explicit_models, set):
        raise BackupValidationError(
            "Clean-target restore identity tracking is unavailable."
        )
    session.flush()
    connection = session.connection()
    for model in sorted(explicit_models, key=lambda value: value.__table__.key):
        table = model.__table__
        primary_keys = list(table.primary_key.columns)
        if len(primary_keys) != 1 or primary_keys[0].name != "id":
            raise BackupValidationError(
                f"Clean-target restore cannot synchronize {table.fullname} identity."
            )
        primary_key = primary_keys[0]
        table_name = table.fullname
        sequence_name = connection.execute(
            text(
                "SELECT pg_get_serial_sequence(:table_name, :column_name)"
            ),
            {"table_name": table_name, "column_name": primary_key.name},
        ).scalar_one_or_none()
        if sequence_name is None:
            continue
        maximum_id = connection.execute(
            select(primary_key).order_by(primary_key.desc()).limit(1)
        ).scalar_one_or_none()
        if not isinstance(maximum_id, int):
            raise BackupValidationError(
                f"Clean-target restore cannot resolve {table.fullname} maximum id."
            )
        connection.execute(
            text(
                "SELECT setval(CAST(:sequence_name AS regclass), :maximum_id, true)"
            ),
            {"sequence_name": sequence_name, "maximum_id": maximum_id},
        )


def _upsert(
    session: Session,
    model: type[SQLModel],
    statement: Any,
    payload: dict[str, Any],
) -> SQLModel:
    normalized = model.model_validate(
        _normalize_converged_utc_restore_values(model, payload)
    )
    existing = session.exec(statement).first()
    if existing:
        values = normalized.model_dump(exclude={"id"})
        for key, value in values.items():
            setattr(existing, key, value)
        record = existing
    else:
        values = _restore_insert_values(session, model, normalized)
        record = model(**values)
    session.add(record)
    session.flush()
    return record


def _normalize_converged_utc_restore_values(
    model: type[SQLModel],
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Bind legacy UTC-naive values to TIMESTAMPTZ without session dependence."""

    fields = _CONVERGED_UTC_MODEL_FIELDS.get(model) or _FORM_DELIVERY_UTC_MODEL_FIELDS.get(model)
    if fields is None:
        return payload
    normalized = dict(payload)
    for field in fields:
        value = normalized.get(field)
        if value is None:
            continue
        parsed = _datetime_value(value, f"{model.__table__.key}.{field}")
        normalized[field] = (
            parsed.replace(tzinfo=UTC)
            if parsed.tzinfo is None
            else parsed.astimezone(UTC)
        )
    return normalized


def _restore_immutable_record(
    session: Session,
    model: type[SQLModel],
    statement: Any,
    payload: dict[str, Any],
    *,
    label: str,
) -> SQLModel:
    """Insert a durable record or reuse one exact immutable match."""

    normalized = model.model_validate(
        _normalize_converged_utc_restore_values(model, payload)
    )
    matches = list(session.exec(statement).all())
    if len(matches) > 1:
        raise BackupValidationError(
            f"Target {label} contains duplicate immutable identities; restore was refused."
        )
    existing = matches[0] if matches else None
    if existing is not None:
        expected = _normalized_immutable_projection(normalized)
        observed = _normalized_immutable_projection(existing)
        if observed != expected:
            raise BackupValidationError(
                f"Target {label} immutable state diverges from the backup; restore was refused."
            )
        return existing

    values = _restore_insert_values(session, model, normalized)
    record = model(**values)
    session.add(record)
    session.flush()
    return record


def _normalized_immutable_projection(record: SQLModel) -> dict[str, Any]:
    def normalize(value: Any) -> Any:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
            return value.astimezone(UTC).isoformat()
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    return normalize(record.model_dump(mode="python", exclude={"id"}))


def _require_restore_compatible_form_delivery_mode_prefixes(
    session: Session,
    records: list[dict[str, Any]],
    *,
    website_ids: dict[int, int],
) -> None:
    """Never merge an older mode lineage over a newer or gapped target chain."""

    maximums: dict[tuple[int, str], int] = {}
    for record in records:
        scope = (
            _mapped_id(
                website_ids,
                record["website_id"],
                "website_form_delivery_mode_revisions.website_id",
            ),
            record["form_instance_key"],
        )
        maximums[scope] = max(maximums.get(scope, 0), record["revision"])
    for (website_id, form_instance_key), source_maximum in maximums.items():
        target = list(
            session.exec(
                select(WebsiteFormDeliveryModeRevision)
                .where(
                    WebsiteFormDeliveryModeRevision.website_id == website_id,
                    WebsiteFormDeliveryModeRevision.form_instance_key
                    == form_instance_key,
                )
                .order_by(WebsiteFormDeliveryModeRevision.revision)
            ).all()
        )
        revisions = [record.revision for record in target]
        if revisions != list(range(1, len(target) + 1)):
            raise BackupValidationError(
                "Target form-delivery mode lineage is incomplete or divergent; restore was refused."
            )
        if revisions and revisions[-1] > source_maximum:
            raise BackupValidationError(
                "Target form-delivery mode lineage is newer than the backup; restore was refused."
            )


def _require_restore_compatible_form_recipient_prefixes(
    session: Session,
    records: list[dict[str, Any]],
    *,
    website_ids: dict[int, int],
) -> None:
    """Never merge an older recipient lineage over newer durable evidence."""

    maximums: dict[tuple[int, str, str], int] = {}
    for record in records:
        scope = (
            _mapped_id(
                website_ids,
                record["website_id"],
                "website_form_recipient_revisions.website_id",
            ),
            record["form_instance_key"],
            record["recipient_key"],
        )
        maximums[scope] = max(maximums.get(scope, 0), record["revision"])
    for (
        website_id,
        form_instance_key,
        recipient_key,
    ), source_maximum in maximums.items():
        target = list(
            session.exec(
                select(WebsiteFormRecipientRevision)
                .where(
                    WebsiteFormRecipientRevision.website_id == website_id,
                    WebsiteFormRecipientRevision.form_instance_key
                    == form_instance_key,
                    WebsiteFormRecipientRevision.recipient_key == recipient_key,
                )
                .order_by(WebsiteFormRecipientRevision.revision)
            ).all()
        )
        revisions = [record.revision for record in target]
        if revisions != list(range(1, len(target) + 1)):
            raise BackupValidationError(
                "Target form-recipient lineage is incomplete or divergent; restore was refused."
            )
        if revisions and revisions[-1] > source_maximum:
            raise BackupValidationError(
                "Target form-recipient lineage is newer than the backup; restore was refused."
            )


def _require_restore_compatible_scoped_authorization_prefix(
    target_history: list[ScopedMediaAuthorization],
    *,
    source_max_version: int,
) -> None:
    """Reject newer or structurally divergent target authorization history.

    A backup may populate an empty target or replay an exact prefix, but an older
    backup must never roll a target lineage backward.  Same-version evidence is
    compared separately after every source identity has been remapped.
    """

    if not target_history:
        return
    versions = [row.authorization_version for row in target_history]
    if versions != list(range(1, len(target_history) + 1)):
        raise BackupValidationError(
            "Target scoped-media authorization lineage is incomplete or divergent; restore was refused."
        )
    if versions[-1] > source_max_version:
        raise BackupValidationError(
            "Target scoped-media authorization lineage is newer than the backup; restore was refused."
        )
    current = [row for row in target_history if row.lifecycle_status == "current"]
    if len(current) > 1 or (current and current[0].id != target_history[-1].id):
        raise BackupValidationError(
            "Target scoped-media authorization current state is divergent; restore was refused."
        )
    for index, row in enumerate(target_history):
        expected_predecessor = target_history[index - 1].id if index else None
        if (
            row.supersedes_authorization_id != expected_predecessor
            or (index < len(target_history) - 1 and row.lifecycle_status != "superseded")
        ):
            raise BackupValidationError(
                "Target scoped-media authorization lineage is divergent; restore was refused."
            )


def _restore_scoped_media_authorization(
    session: Session,
    payload: dict[str, Any],
    *,
    source_max_version: int,
) -> ScopedMediaAuthorization:
    """Insert immutable authorization evidence or reuse an exact existing row.

    Generic backup upserts are intentionally forbidden here.  A natural-key
    collision may be idempotently reused only when every immutable decision field
    and both fingerprints match after foreign-key remapping.  Existing rows are
    never rewritten by restore.
    """

    normalized = ScopedMediaAuthorization.model_validate(payload)
    existing = session.exec(
        select(ScopedMediaAuthorization).where(
            ScopedMediaAuthorization.media_requirement_id
            == normalized.media_requirement_id,
            ScopedMediaAuthorization.authorization_version
            == normalized.authorization_version,
        )
    ).first()
    if existing is not None:
        if _scoped_authorization_immutable_restore_projection(
            existing
        ) != _scoped_authorization_immutable_restore_projection(normalized):
            raise BackupValidationError(
                "Target scoped-media authorization same-version evidence differs from the backup; restore was refused."
            )
        if existing.lifecycle_status != normalized.lifecycle_status:
            may_extend_exact_prefix = (
                existing.lifecycle_status == "current"
                and normalized.lifecycle_status == "superseded"
                and existing.authorization_version < source_max_version
            )
            if not may_extend_exact_prefix:
                raise BackupValidationError(
                    "Target scoped-media authorization lifecycle differs from the backup; restore was refused."
                )
            existing.lifecycle_status = "superseded"
            existing.updated_at = normalized.updated_at
            session.add(existing)
            session.flush()
        return existing

    values = _restore_insert_values(
        session,
        ScopedMediaAuthorization,
        normalized,
    )
    record = ScopedMediaAuthorization(**values)
    session.add(record)
    session.flush()
    return record


def _scoped_authorization_immutable_restore_projection(
    record: ScopedMediaAuthorization,
) -> tuple[Any, ...]:
    """Return exact immutable authorization evidence in comparable form."""

    return (
        record.website_id,
        record.site_plan_id,
        record.planned_page_id,
        record.generated_page_id,
        record.media_requirement_id,
        record.requirement_version,
        record.placement_key,
        record.placement_contract_version,
        record.image_metadata_id,
        record.media_version,
        record.asset_checksum_sha256,
        record.approval_version,
        record.asset_approved_by,
        _comparable_datetime(record.asset_approved_at),
        record.approval_fingerprint,
        record.page_image_assignment_id,
        record.assignment_version,
        record.reuse_policy,
        tuple(record.authorization_terms),
        record.authorized_by,
        record.authorization_rationale,
        _comparable_datetime(record.authorized_at),
        record.authorization_version,
        record.authorization_fingerprint,
        record.supersedes_authorization_id,
    )


def _record_id(record: dict[str, Any], group: str) -> int:
    record_id = record.get("id")
    if not isinstance(record_id, int):
        raise BackupValidationError(f"Every '{group}' record must have an integer id.")
    return record_id


def _restore_theme_source_binding(
    source_snapshot: Any,
    *,
    website_ids: dict[int, int],
    theme_ids: dict[int, int],
    selection_ids: dict[int, int],
) -> dict[str, Any]:
    """Remap durable Theme identities embedded in composition source bindings."""

    if not isinstance(source_snapshot, dict):
        raise BackupValidationError(
            "Backup Page Composition source snapshot must be an object."
        )
    restored = dict(source_snapshot)
    theme_source = restored.get("theme")
    if theme_source is None:
        return restored
    if not isinstance(theme_source, dict):
        raise BackupValidationError(
            "Backup Page Composition Theme source binding must be an object."
        )
    binding = dict(theme_source)
    if binding.get("website_id") is not None:
        binding["website_id"] = _mapped_id(
            website_ids, binding["website_id"], "page_compositions.theme.website_id"
        )
    if binding.get("theme_id") is not None:
        binding["theme_id"] = _mapped_id(
            theme_ids, binding["theme_id"], "page_compositions.theme.theme_id"
        )
    for field in ("selection_id", "theme_selection_id"):
        if binding.get(field) is not None:
            binding[field] = _mapped_id(
                selection_ids,
                binding[field],
                f"page_compositions.theme.{field}",
            )
    restored["theme"] = binding
    return restored


def _restore_composition_instance_key(
    value: Any,
    *,
    requirement_ids: dict[int, int],
    assignment_ids: dict[int, int],
) -> Any:
    """Remap the derived durable id in governed or legacy media instance keys."""

    if not isinstance(value, str):
        return value
    prefixes = (
        ("media_placement:requirement-", requirement_ids, "media requirement"),
        ("media_placement:assignment-", assignment_ids, "media assignment"),
    )
    for prefix, mapping, label in prefixes:
        if not value.startswith(prefix):
            continue
        raw_id = value[len(prefix) :]
        try:
            old_id = int(raw_id)
        except ValueError as exc:
            raise BackupValidationError(
                f"Backup Page Composition {label} instance key is malformed."
            ) from exc
        return f"{prefix}{_mapped_id(mapping, old_id, f'page_compositions.{label}_instance_key')}"
    return value


def _restore_composition_component_bindings(
    components: Any,
    *,
    website_ids: dict[int, int],
    navigation_set_ids: dict[int, int],
    generated_page_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    internal_link_intent_ids: dict[int, int],
    requirement_ids: dict[int, int],
    assignment_ids: dict[int, int],
) -> list[dict[str, Any]]:
    """Remap every durable identity embedded in composition components."""

    if not isinstance(components, list) or not all(
        isinstance(item, dict) for item in components
    ):
        raise BackupValidationError(
            "Backup Page Composition component records must be a list of objects."
        )
    restored = deepcopy(components)
    for component in restored:
        if component.get("instance_key") is not None:
            component["instance_key"] = _restore_composition_instance_key(
                component["instance_key"],
                requirement_ids=requirement_ids,
                assignment_ids=assignment_ids,
            )
        bindings = component.get("input_bindings")
        if bindings is None:
            continue
        if not isinstance(bindings, dict):
            raise BackupValidationError(
                "Backup Page Composition component bindings must be an object."
            )
        for field, mapping in (
            ("website_id", website_ids),
            ("navigation_set_id", navigation_set_ids),
            ("generated_page_id", generated_page_ids),
            ("planned_page_id", planned_page_ids),
            ("target_planned_page_id", planned_page_ids),
        ):
            if bindings.get(field) is not None:
                bindings[field] = _mapped_id(
                    mapping,
                    bindings[field],
                    f"page_compositions.generated_components.{field}",
                )
        for field, mapping in (
            ("internal_link_intent_ids", internal_link_intent_ids),
            ("draft_related_page_ids", planned_page_ids),
        ):
            if field not in bindings:
                continue
            values = bindings[field]
            if not isinstance(values, list):
                raise BackupValidationError(
                    f"Backup Page Composition component {field} must be a list."
                )
            bindings[field] = [
                _mapped_id(
                    mapping,
                    value,
                    f"page_compositions.generated_components.{field}",
                )
                for value in values
            ]
        if bindings.get("media_requirement_id") is not None:
            bindings["media_requirement_id"] = _mapped_id(
                requirement_ids,
                bindings["media_requirement_id"],
                "page_compositions.generated_components.media_requirement_id",
            )
        if bindings.get("page_image_assignment_id") is not None:
            bindings["page_image_assignment_id"] = _mapped_id(
                assignment_ids,
                bindings["page_image_assignment_id"],
                "page_compositions.generated_components.page_image_assignment_id",
            )
    return restored


def _restore_composition_target_binding(
    value: Any,
    *,
    website_ids: dict[int, int],
    site_plan_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    generated_page_ids: dict[int, int],
    field: str,
) -> Any:
    if type(value) is int:
        # Legacy draft-graph snapshots stored only the target Planned Page id.
        # Preserve that shape while still remapping the embedded identity.
        return _mapped_id(
            planned_page_ids,
            value,
            f"page_compositions.{field}.planned_page_id",
        )
    if not isinstance(value, dict):
        raise BackupValidationError(
            f"Backup Page Composition {field} target binding must be an object or legacy Planned Page id."
        )
    restored = dict(value)
    for key, mapping in (
        ("website_id", website_ids),
        ("site_plan_id", site_plan_ids),
        ("planned_page_id", planned_page_ids),
        ("generated_page_id", generated_page_ids),
    ):
        if restored.get(key) is not None:
            restored[key] = _mapped_id(
                mapping,
                restored[key],
                f"page_compositions.{field}.{key}",
            )
    return restored


def _restore_composition_source_binding(
    session: Session,
    source_snapshot: Any,
    *,
    website_ids: dict[int, int],
    business_ids: dict[int, int],
    website_identity_ids: dict[int, int],
    site_plan_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    generated_page_ids: dict[int, int],
    service_ids: dict[int, int],
    city_ids: dict[int, int],
    county_ids: dict[int, int],
    navigation_set_ids: dict[int, int],
    navigation_item_ids: dict[int, int],
    internal_link_intent_ids: dict[int, int],
    brand_asset_ids: dict[int, int],
    planning_record_ids: dict[int, int],
    requirement_ids: dict[int, int],
    assignment_ids: dict[int, int],
    image_ids: dict[int, int],
    authorization_ids: dict[int, int],
    authorization_fingerprints: dict[int, str],
) -> dict[str, Any]:
    """Remap every durable identity embedded in composition source snapshots."""

    if not isinstance(source_snapshot, dict):
        raise BackupValidationError(
            "Backup Page Composition source snapshot must be an object."
        )
    restored = deepcopy(source_snapshot)
    for field, mapping in (
        ("website_id", website_ids),
        ("site_plan_id", site_plan_ids),
        ("planned_page_id", planned_page_ids),
        ("generated_page_id", generated_page_ids),
        ("website_identity_id", website_identity_ids),
    ):
        if restored.get(field) is not None:
            restored[field] = _mapped_id(
                mapping,
                restored[field],
                f"page_compositions.source_snapshot.{field}",
            )

    if restored.get("website_context_hash") is not None:
        from app.services.website_context import build_website_context

        generated_page_id = restored.get("generated_page_id")
        if not isinstance(generated_page_id, int):
            raise BackupValidationError(
                "Backup Page Composition website context lacks a Generated Page binding."
            )
        restored["website_context_hash"] = _canonical_json_hash(
            build_website_context(
                session,
                page_id=generated_page_id,
            ).model_dump(mode="json")
        )

    navigation_sets = restored.get("navigation_sets")
    if navigation_sets is not None:
        if not isinstance(navigation_sets, list):
            raise BackupValidationError(
                "Backup Page Composition Navigation Sets must be a list."
            )
        for item in navigation_sets:
            if not isinstance(item, dict):
                raise BackupValidationError(
                    "Backup Page Composition Navigation Set binding must be an object."
                )
            if item.get("id") is not None:
                item["id"] = _mapped_id(
                    navigation_set_ids,
                    item["id"],
                    "page_compositions.navigation_sets.id",
                )

    navigation_items = restored.get("navigation_items")
    if navigation_items is not None:
        if not isinstance(navigation_items, list):
            raise BackupValidationError(
                "Backup Page Composition Navigation Items must be a list."
            )
        for item in navigation_items:
            if not isinstance(item, dict):
                raise BackupValidationError(
                    "Backup Page Composition Navigation Item binding must be an object."
                )
            if item.get("id") is not None:
                item["id"] = _mapped_id(
                    navigation_item_ids,
                    item["id"],
                    "page_compositions.navigation_items.id",
                )
            if item.get("navigation_set_id") is not None:
                item["navigation_set_id"] = _mapped_id(
                    navigation_set_ids,
                    item["navigation_set_id"],
                    "page_compositions.navigation_items.navigation_set_id",
                )
            if item.get("parent_navigation_item_id") is not None:
                item["parent_navigation_item_id"] = _mapped_id(
                    navigation_item_ids,
                    item["parent_navigation_item_id"],
                    "page_compositions.navigation_items.parent_navigation_item_id",
                )
            if item.get("target") is not None:
                item["target"] = _restore_composition_target_binding(
                    item["target"],
                    website_ids=website_ids,
                    site_plan_ids=site_plan_ids,
                    planned_page_ids=planned_page_ids,
                    generated_page_ids=generated_page_ids,
                    field="navigation_items.target",
                )

    internal_links = restored.get("internal_links")
    if internal_links is not None:
        if not isinstance(internal_links, list):
            raise BackupValidationError(
                "Backup Page Composition Internal Links must be a list."
            )
        for item in internal_links:
            if not isinstance(item, dict):
                raise BackupValidationError(
                    "Backup Page Composition Internal Link binding must be an object."
                )
            if item.get("id") is not None:
                item["id"] = _mapped_id(
                    internal_link_intent_ids,
                    item["id"],
                    "page_compositions.internal_links.id",
                )
            if item.get("target") is not None:
                item["target"] = _restore_composition_target_binding(
                    item["target"],
                    website_ids=website_ids,
                    site_plan_ids=site_plan_ids,
                    planned_page_ids=planned_page_ids,
                    generated_page_ids=generated_page_ids,
                    field="internal_links.target",
                )

    draft_related_targets = restored.get("draft_related_targets")
    if draft_related_targets is not None:
        if not isinstance(draft_related_targets, list):
            raise BackupValidationError(
                "Backup Page Composition draft-related targets must be a list."
            )
        restored["draft_related_targets"] = [
            _restore_composition_target_binding(
                item,
                website_ids=website_ids,
                site_plan_ids=site_plan_ids,
                planned_page_ids=planned_page_ids,
                generated_page_ids=generated_page_ids,
                field="draft_related_targets",
            )
            for item in draft_related_targets
        ]

    media_assignments = restored.get("media_assignments")
    if media_assignments is not None:
        if not isinstance(media_assignments, list):
            raise BackupValidationError(
                "Backup Page Composition media assignments must be a list."
            )
        for item in media_assignments:
            if not isinstance(item, dict):
                raise BackupValidationError(
                    "Backup Page Composition media assignment binding must be an object."
                )
            if item.get("id") is not None:
                item["id"] = _mapped_id(
                    assignment_ids,
                    item["id"],
                    "page_compositions.media_assignments.id",
                )
            if item.get("image_metadata_id") is not None:
                item["image_metadata_id"] = _mapped_id(
                    image_ids,
                    item["image_metadata_id"],
                    "page_compositions.media_assignments.image_metadata_id",
                )

    identity_assets = restored.get("website_identity_assets")
    if identity_assets is not None:
        if not isinstance(identity_assets, list):
            raise BackupValidationError(
                "Backup Page Composition Website Identity assets must be a list."
            )
        for item in identity_assets:
            if not isinstance(item, dict):
                raise BackupValidationError(
                    "Backup Page Composition Website Identity asset binding must be an object."
                )
            if item.get("asset_id") is not None:
                item["asset_id"] = _mapped_id(
                    brand_asset_ids,
                    item["asset_id"],
                    "page_compositions.website_identity_assets.asset_id",
                )

    page_media = restored.get("page_media")
    if page_media is None:
        return restored
    if not isinstance(page_media, dict):
        raise BackupValidationError(
            "Backup Page Composition Page Media source binding must be an object."
        )
    planning = page_media.get("planning_record")
    if planning is not None:
        if not isinstance(planning, dict):
            raise BackupValidationError(
                "Backup Page Composition Page Media planning binding must be an object."
            )
        for field in ("id", "record_id", "planning_record_id"):
            if planning.get(field) is not None:
                planning[field] = _mapped_id(
                    planning_record_ids,
                    planning[field],
                    f"page_compositions.page_media.planning_record.{field}",
                )
        planned_page = planning.get("planned_page")
        if planned_page is not None:
            if not isinstance(planned_page, dict):
                raise BackupValidationError(
                    "Backup Page Composition Page Media Planned Page binding must be an object."
                )
            for field, mapping in (
                ("id", planned_page_ids),
                ("service_id", service_ids),
                ("city_id", city_ids),
                ("county_id", county_ids),
                ("generated_page_id", generated_page_ids),
            ):
                if planned_page.get(field) is not None:
                    planned_page[field] = _mapped_id(
                        mapping,
                        planned_page[field],
                        f"page_compositions.page_media.planning_record.planned_page.{field}",
                    )
        suggestions = planning.get("suggestions")
        if suggestions is not None:
            if not isinstance(suggestions, list):
                raise BackupValidationError(
                    "Backup Page Composition Page Media suggestions must be a list."
                )
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    raise BackupValidationError(
                        "Backup Page Composition Page Media suggestion binding must be an object."
                    )
                for field, mapping in (
                    ("website_id", website_ids),
                    ("business_id", business_ids),
                    ("site_plan_id", site_plan_ids),
                    ("planned_page_id", planned_page_ids),
                ):
                    if suggestion.get(field) is not None:
                        suggestion[field] = _mapped_id(
                            mapping,
                            suggestion[field],
                            f"page_compositions.page_media.planning_record.suggestions.{field}",
                        )
    requirements = page_media.get("requirements", [])
    assignments = page_media.get("assignments", [])
    if not isinstance(requirements, list) or not isinstance(assignments, list):
        raise BackupValidationError(
            "Backup Page Composition Page Media requirements and assignments must be lists."
        )
    for requirement in requirements:
        if not isinstance(requirement, dict):
            raise BackupValidationError(
                "Backup Page Composition Page Media requirement binding must be an object."
            )
        requirement["id"] = _mapped_id(
            requirement_ids,
            requirement.get("id"),
            "page_compositions.page_media.requirements.id",
        )
        if requirement.get("planning_record_id") is not None:
            requirement["planning_record_id"] = _mapped_id(
                planning_record_ids,
                requirement["planning_record_id"],
                "page_compositions.page_media.requirements.planning_record_id",
            )
    for assignment in assignments:
        if not isinstance(assignment, dict):
            raise BackupValidationError(
                "Backup Page Composition Page Media assignment binding must be an object."
            )
        assignment["requirement_id"] = _mapped_id(
            requirement_ids,
            assignment.get("requirement_id"),
            "page_compositions.page_media.assignments.requirement_id",
        )
        assignment["assignment_id"] = _mapped_optional_id(
            assignment_ids,
            assignment.get("assignment_id"),
            "page_compositions.page_media.assignments.assignment_id",
        )
        assignment["asset_id"] = _mapped_optional_id(
            image_ids,
            assignment.get("asset_id"),
            "page_compositions.page_media.assignments.asset_id",
        )
        if assignment.get("authorization_id") is not None:
            old_authorization_id = assignment["authorization_id"]
            assignment["authorization_id"] = _mapped_id(
                authorization_ids,
                old_authorization_id,
                "page_compositions.page_media.assignments.authorization_id",
            )
            try:
                assignment["authorization_fingerprint"] = (
                    authorization_fingerprints[old_authorization_id]
                )
            except KeyError as exc:
                raise BackupValidationError(
                    "Backup Page Composition authorization fingerprint cannot be remapped."
                ) from exc
        if assignment.get("authorization_assignment_id") is not None:
            assignment["authorization_assignment_id"] = _mapped_id(
                assignment_ids,
                assignment["authorization_assignment_id"],
                "page_compositions.page_media.assignments.authorization_assignment_id",
            )
    return restored


def _remap_site_connection_suggestion_key(
    value: Any,
    planned_page_ids: dict[int, int],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise BackupValidationError(
            "Backup Site Connection suggestion key must be text."
        )
    parts = value.split(":")
    if len(parts) == 3 and parts[0] == "navigation":
        try:
            old_target = int(parts[2])
        except ValueError as exc:
            raise BackupValidationError(
                "Backup Navigation suggestion key is malformed."
            ) from exc
        target = _mapped_id(
            planned_page_ids,
            old_target,
            "navigation suggestion target",
        )
        return f"navigation:{parts[1]}:{target}"
    if len(parts) == 4 and parts[0] == "internal-link":
        try:
            old_source = int(parts[1])
            old_target = int(parts[2])
        except ValueError as exc:
            raise BackupValidationError(
                "Backup Internal Link suggestion key is malformed."
            ) from exc
        source = _mapped_id(
            planned_page_ids,
            old_source,
            "internal-link suggestion source",
        )
        target = _mapped_id(
            planned_page_ids,
            old_target,
            "internal-link suggestion target",
        )
        return f"internal-link:{source}:{target}:{parts[3]}"
    raise BackupValidationError("Backup Site Connection suggestion key is malformed.")


def _restore_site_connection_planning_payload(
    record: dict[str, Any],
    planned_page_ids: dict[int, int],
) -> dict[str, Any]:
    restored = dict(record)
    navigation_suggestions: list[dict[str, Any]] = []
    for value in record.get("generated_navigation_suggestions", []):
        if not isinstance(value, dict):
            raise BackupValidationError(
                "Backup Navigation suggestions must contain objects."
            )
        item = dict(value)
        item["target_planned_page_id"] = _mapped_id(
            planned_page_ids,
            value.get("target_planned_page_id"),
            "generated_navigation_suggestions.target_planned_page_id",
        )
        item["suggestion_key"] = (
            f"navigation:{item.get('set_type')}:{item['target_planned_page_id']}"
        )
        navigation_suggestions.append(item)
    restored["generated_navigation_suggestions"] = navigation_suggestions

    link_suggestions: list[dict[str, Any]] = []
    for value in record.get("generated_internal_link_suggestions", []):
        if not isinstance(value, dict):
            raise BackupValidationError(
                "Backup Internal Link suggestions must contain objects."
            )
        item = dict(value)
        item["source_planned_page_id"] = _mapped_id(
            planned_page_ids,
            value.get("source_planned_page_id"),
            "generated_internal_link_suggestions.source_planned_page_id",
        )
        item["target_planned_page_id"] = _mapped_id(
            planned_page_ids,
            value.get("target_planned_page_id"),
            "generated_internal_link_suggestions.target_planned_page_id",
        )
        item["suggestion_key"] = (
            f"internal-link:{item['source_planned_page_id']}:"
            f"{item['target_planned_page_id']}:{item.get('relationship_type')}"
        )
        link_suggestions.append(item)
    restored["generated_internal_link_suggestions"] = link_suggestions

    snapshot = record.get("source_snapshot")
    if isinstance(snapshot, dict):
        restored_snapshot = dict(snapshot)
        planned_pages: list[dict[str, Any]] = []
        for value in snapshot.get("planned_pages", []):
            if not isinstance(value, dict):
                raise BackupValidationError(
                    "Backup Site Connection source snapshot contains an invalid page."
                )
            page = dict(value)
            page["id"] = _mapped_id(
                planned_page_ids,
                value.get("id"),
                "site_connection_planning_records.source_snapshot.planned_pages.id",
            )
            page["parent_planned_page_id"] = _mapped_optional_id(
                planned_page_ids,
                value.get("parent_planned_page_id"),
                "site_connection_planning_records.source_snapshot.parent_planned_page_id",
            )
            planned_pages.append(page)
        restored_snapshot["planned_pages"] = planned_pages
        restored["source_snapshot"] = restored_snapshot
    return restored


def _restore_page_media_planning_payload(
    record: dict[str, Any],
    *,
    website_ids: dict[int, int],
    business_ids: dict[int, int],
    site_plan_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    generated_page_ids: dict[int, int],
    service_ids: dict[int, int],
    city_ids: dict[int, int],
    county_ids: dict[int, int],
) -> dict[str, Any]:
    """Remap durable identities embedded in page-media planning snapshots."""

    restored = dict(record)
    suggestions: list[dict[str, Any]] = []
    for value in record.get("generated_media_suggestions", []):
        if not isinstance(value, dict):
            raise BackupValidationError(
                "Backup Page Media suggestions must contain objects."
            )
        item = dict(value)
        item["website_id"] = _mapped_id(
            website_ids,
            value.get("website_id"),
            "website_media_planning_records.generated_media_suggestions.website_id",
        )
        item["business_id"] = _mapped_id(
            business_ids,
            value.get("business_id"),
            "website_media_planning_records.generated_media_suggestions.business_id",
        )
        item["site_plan_id"] = _mapped_id(
            site_plan_ids,
            value.get("site_plan_id"),
            "website_media_planning_records.generated_media_suggestions.site_plan_id",
        )
        item["planned_page_id"] = _mapped_id(
            planned_page_ids,
            value.get("planned_page_id"),
            "website_media_planning_records.generated_media_suggestions.planned_page_id",
        )
        suggestions.append(item)
    restored["generated_media_suggestions"] = suggestions

    source_snapshot = record.get("source_snapshot")
    if not isinstance(source_snapshot, dict):
        raise BackupValidationError(
            "Backup Page Media planning source snapshot must be an object."
        )
    snapshot = dict(source_snapshot)
    snapshot["website_id"] = _mapped_id(
        website_ids,
        source_snapshot.get("website_id"),
        "website_media_planning_records.source_snapshot.website_id",
    )
    snapshot["site_plan_id"] = _mapped_id(
        site_plan_ids,
        source_snapshot.get("site_plan_id"),
        "website_media_planning_records.source_snapshot.site_plan_id",
    )
    planned_pages: list[dict[str, Any]] = []
    for value in source_snapshot.get("planned_pages", []):
        if not isinstance(value, dict):
            raise BackupValidationError(
                "Backup Page Media source snapshot contains an invalid Planned Page."
            )
        page = dict(value)
        page["id"] = _mapped_id(
            planned_page_ids,
            value.get("id"),
            "website_media_planning_records.source_snapshot.planned_pages.id",
        )
        page["service_id"] = _mapped_optional_id(
            service_ids,
            value.get("service_id"),
            "website_media_planning_records.source_snapshot.planned_pages.service_id",
        )
        page["city_id"] = _mapped_optional_id(
            city_ids,
            value.get("city_id"),
            "website_media_planning_records.source_snapshot.planned_pages.city_id",
        )
        page["county_id"] = _mapped_optional_id(
            county_ids,
            value.get("county_id"),
            "website_media_planning_records.source_snapshot.planned_pages.county_id",
        )
        page["generated_page_id"] = _mapped_optional_id(
            generated_page_ids,
            value.get("generated_page_id"),
            "website_media_planning_records.source_snapshot.planned_pages.generated_page_id",
        )
        planned_pages.append(page)
    snapshot["planned_pages"] = planned_pages
    restored["source_snapshot"] = snapshot
    restored["source_hash"] = _canonical_json_hash(snapshot)
    return restored


def _canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _backup_version_before(value: str, minimum: str) -> bool:
    """Compare validated Atlas backup versions without lexicographic ordering."""

    return tuple(int(part) for part in value.split(".")) < tuple(
        int(part) for part in minimum.split(".")
    )


def _canonicalize_navigation_decision_timestamps(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    """Keep timezone-aware navigation decisions stable across SQL backends."""

    for group in _UTC_NAVIGATION_DECISION_GROUPS:
        for record in data.get(group, []):
            value = record.get("decided_at")
            if value is None:
                continue
            parsed = _datetime_value(value, f"{group}.decided_at")
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            record["decided_at"] = (
                parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
            )


def _canonicalize_converged_utc_timestamps(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    """Normalize only the 24 UTC timestamp fields converged by revision 0046."""

    from app.services.page_composition import canonical_utc_timestamp

    for group, fields in _CONVERGED_UTC_TIMESTAMP_FIELDS.items():
        for record in data.get(group, []):
            for field in fields:
                value = record.get(field)
                if value is None:
                    continue
                record[field] = canonical_utc_timestamp(
                    _datetime_value(value, f"{group}.{field}")
                )


def _canonicalize_form_delivery_utc_timestamps(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    """Normalize revision 0047 form-delivery timestamps as explicit UTC."""

    for group, fields in _FORM_DELIVERY_UTC_TIMESTAMP_FIELDS.items():
        for record in data.get(group, []):
            for field in fields:
                value = record.get(field)
                if value is None:
                    continue
                parsed = _datetime_value(value, f"{group}.{field}")
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                record[field] = parsed.astimezone(UTC).isoformat()


def _canonical_theme_datetime(value: Any, field: str) -> str | None:
    if value is None:
        return None
    parsed = _datetime_value(value, field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _theme_family_fingerprint_payload(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "family_key": record.get("family_key"),
        "display_name": record.get("display_name"),
        "description": record.get("description"),
        "provider_source_identity": record.get("provider_source_identity"),
        "lifecycle_status": record.get("lifecycle_status"),
        "created_by": record.get("created_by"),
        "retired_by": record.get("retired_by"),
        "retired_at": _canonical_theme_datetime(
            record.get("retired_at"),
            "theme_families.retired_at",
        ),
    }


def _theme_family_version_fingerprint_payload(
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "theme_family_id": record.get("theme_family_id"),
        "version": record.get("version"),
        "lifecycle_status": record.get("lifecycle_status"),
        "production_ready": record.get("production_ready"),
        "source_commit": record.get("source_commit"),
        "compatibility_identity": record.get("compatibility_identity"),
        "supported_component_contracts": record.get(
            "supported_component_contracts"
        ),
        "created_by": record.get("created_by"),
        "retired_by": record.get("retired_by"),
        "retired_at": _canonical_theme_datetime(
            record.get("retired_at"),
            "theme_family_versions.retired_at",
        ),
        "supersedes_theme_family_version_id": record.get(
            "supersedes_theme_family_version_id"
        ),
    }


def _website_theme_configuration_fingerprint_payload(
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "website_id": record.get("website_id"),
        "business_id": record.get("business_id"),
        "theme_family_version_id": record.get("theme_family_version_id"),
        "configuration_key": record.get("configuration_key"),
        "version": record.get("version"),
        "lifecycle_status": record.get("lifecycle_status"),
        "created_by": record.get("created_by"),
        "updated_by": record.get("updated_by"),
        "creation_rationale": record.get("creation_rationale"),
        "approved_by": record.get("approved_by"),
        "approved_at": _canonical_theme_datetime(
            record.get("approved_at"),
            "website_theme_configurations.approved_at",
        ),
        "activated_by": record.get("activated_by"),
        "activated_at": _canonical_theme_datetime(
            record.get("activated_at"),
            "website_theme_configurations.activated_at",
        ),
        "rollback_by": record.get("rollback_by"),
        "rollback_at": _canonical_theme_datetime(
            record.get("rollback_at"),
            "website_theme_configurations.rollback_at",
        ),
        "materialized_theme_id": record.get("materialized_theme_id"),
        "website_theme_selection_id": record.get("website_theme_selection_id"),
        "supersedes_configuration_id": record.get(
            "supersedes_configuration_id"
        ),
    }


def _theme_component_configuration_fingerprint_payload(
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "website_theme_configuration_id": record.get(
            "website_theme_configuration_id"
        ),
        "website_id": record.get("website_id"),
        "planned_page_id": record.get("planned_page_id"),
        "theme_family_version_id": record.get("theme_family_version_id"),
        "component_instance_key": record.get("component_instance_key"),
        "component_key": record.get("component_key"),
        "component_contract_version": record.get("component_contract_version"),
        "revision": record.get("revision"),
        "scope_type": record.get("scope_type"),
        "lifecycle_status": record.get("lifecycle_status"),
        "enabled": record.get("enabled"),
        "variant": record.get("variant"),
        "placement": record.get("placement"),
        "responsive_visibility": record.get("responsive_visibility"),
        "configuration_payload": record.get("configuration_payload"),
        "effective_at": _canonical_theme_datetime(
            record.get("effective_at"),
            "website_theme_component_configurations.effective_at",
        ),
        "expires_at": _canonical_theme_datetime(
            record.get("expires_at"),
            "website_theme_component_configurations.expires_at",
        ),
        "approval_identity": record.get("approval_identity"),
        "created_by": record.get("created_by"),
        "updated_by": record.get("updated_by"),
        "activation_identity": record.get("activation_identity"),
        "activated_at": _canonical_theme_datetime(
            record.get("activated_at"),
            "website_theme_component_configurations.activated_at",
        ),
        "rollback_identity": record.get("rollback_identity"),
        "rollback_at": _canonical_theme_datetime(
            record.get("rollback_at"),
            "website_theme_component_configurations.rollback_at",
        ),
        "destination_component_configuration_id": record.get(
            "destination_component_configuration_id"
        ),
        "overrides_component_configuration_id": record.get(
            "overrides_component_configuration_id"
        ),
        "supersedes_component_configuration_id": record.get(
            "supersedes_component_configuration_id"
        ),
    }


def _theme_configuration_audit_hash_payload(
    record: dict[str, Any],
) -> dict[str, Any]:
    return {
        "theme_family_id": record.get("theme_family_id"),
        "theme_family_version_id": record.get("theme_family_version_id"),
        "website_theme_configuration_id": record.get(
            "website_theme_configuration_id"
        ),
        "component_configuration_id": record.get("component_configuration_id"),
        "action_type": record.get("action_type"),
        "actor": record.get("actor"),
        "rationale": record.get("rationale"),
        "snapshot": record.get("snapshot"),
        "created_at": _canonical_theme_datetime(
            record.get("created_at"),
            "theme_configuration_audits.created_at",
        ),
    }


def _restore_theme_configuration_audit_snapshot(
    snapshot: Any,
    *,
    website_ids: dict[int, int],
    business_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    theme_ids: dict[int, int],
    selection_ids: dict[int, int],
    family_ids: dict[int, int],
    family_version_ids: dict[int, int],
    configuration_ids: dict[int, int],
    component_ids: dict[int, int],
) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise BackupValidationError(
            "Theme configuration audit snapshot must be an object."
        )
    restored = deepcopy(snapshot)
    mappings = (
        ("website_id", website_ids),
        ("business_id", business_ids),
        ("planned_page_id", planned_page_ids),
        ("materialized_theme_id", theme_ids),
        ("website_theme_selection_id", selection_ids),
        ("theme_family_id", family_ids),
        ("theme_family_version_id", family_version_ids),
        ("supersedes_theme_family_version_id", family_version_ids),
        ("website_theme_configuration_id", configuration_ids),
        ("supersedes_configuration_id", configuration_ids),
        ("destination_component_configuration_id", component_ids),
        ("overrides_component_configuration_id", component_ids),
        ("supersedes_component_configuration_id", component_ids),
    )
    for field, mapping in mappings:
        if restored.get(field) is not None:
            restored[field] = _mapped_id(
                mapping,
                restored[field],
                f"theme_configuration_audits.snapshot.{field}",
            )
    return restored


def _restore_form_delivery_audit_snapshot(
    snapshot: Any,
    *,
    website_ids: dict[int, int],
    component_ids: dict[int, int],
    mode_revision_ids: dict[int, int],
    recipient_revision_ids: dict[int, int],
) -> dict[str, Any]:
    """Remap only the identities allowed by the fixed safe audit projection."""

    if not isinstance(snapshot, dict):
        raise BackupValidationError(
            "Form-delivery configuration audit snapshot must be an object."
        )
    restored = deepcopy(snapshot)
    target = restored.get("target")
    if target == "mode_revision":
        target_mapping = mode_revision_ids
    elif target == "recipient_revision":
        target_mapping = recipient_revision_ids
    else:
        raise BackupValidationError(
            "Form-delivery configuration audit snapshot has an invalid target."
        )
    mappings = (
        ("target_id", target_mapping),
        ("website_id", website_ids),
        ("form_component_configuration_id", component_ids),
    )
    for field, mapping in mappings:
        restored[field] = _mapped_id(
            mapping,
            restored.get(field),
            f"form_delivery_configuration_audits.snapshot.{field}",
        )
    return restored


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


def _qa_projection_from_durable_result(
    record: GeneratedPageQAResult,
) -> dict[str, Any]:
    """Rebuild redundant projections from restored immutable QA evidence."""

    if record.id is None or record.evaluated_at is None:
        raise BackupValidationError(
            "Restored durable QA evidence lacks an identity or evaluation timestamp."
        )
    return {
        "qa_result_id": record.id,
        "page_id": record.generated_page_id,
        "website_id": record.website_id,
        "site_plan_id": record.site_plan_id,
        "planned_page_id": record.planned_page_id,
        "latest_generated_page_revision_id": record.latest_generated_page_revision_id,
        "content_hash": record.content_hash,
        "source_hash": record.source_hash,
        "page_composition_id": record.page_composition_id,
        "composition_version": record.composition_version,
        "composition_source_hash": record.composition_source_hash,
        "qa_algorithm_key": record.qa_algorithm_key,
        "qa_algorithm_version": record.qa_algorithm_version,
        "qa_ruleset_key": record.qa_ruleset_key,
        "qa_ruleset_version": record.qa_ruleset_version,
        "qa_ruleset_hash": record.qa_ruleset_hash,
        "readiness_status": record.readiness_status,
        "checked_at": _canonical_qa_timestamp(record.evaluated_at),
        "passed_count": record.passed_count,
        "warning_count": record.warning_count,
        "failed_count": record.failed_count,
        "checks": deepcopy(record.check_payload or []),
        "result_hash": record.result_hash,
        "lifecycle_status": "current",
        "currentness_status": "current_exact_identity_match",
        "currentness_reasons": [],
    }


def _restore_qa_page_identity(
    value: Any,
    *,
    generated_page_ids: dict[int, int],
    field: str,
    website_ids: dict[int, int] | None = None,
    site_plan_ids: dict[int, int] | None = None,
    planned_page_ids: dict[int, int] | None = None,
    generated_page_revision_ids: dict[int, int] | None = None,
    page_composition_ids: dict[int, int] | None = None,
    qa_result_ids: dict[int, int] | None = None,
    qa_result_hashes: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """Remap every explicit identity in a persisted QA projection."""

    if value is None:
        return None
    if not isinstance(value, dict):
        raise BackupValidationError(f"Backup contains an invalid object in {field}.")
    old_page_id = value.get("page_id")
    restored = deepcopy(value)
    restored["page_id"] = _mapped_id(generated_page_ids, old_page_id, field)
    for key, mapping in (
        ("website_id", website_ids),
        ("site_plan_id", site_plan_ids),
        ("planned_page_id", planned_page_ids),
        ("latest_generated_page_revision_id", generated_page_revision_ids),
        ("page_composition_id", page_composition_ids),
    ):
        if key in restored and mapping is not None:
            restored[key] = _mapped_optional_id(
                mapping,
                restored.get(key),
                f"{field.rsplit('.', 1)[0]}.{key}",
            )
    old_result_id = restored.get("qa_result_id")
    if old_result_id is not None and qa_result_ids is not None:
        restored["qa_result_id"] = _mapped_id(
            qa_result_ids,
            old_result_id,
            f"{field.rsplit('.', 1)[0]}.qa_result_id",
        )
    old_result_hash = restored.get("result_hash")
    if (
        isinstance(old_result_hash, str)
        and qa_result_hashes is not None
        and old_result_hash in qa_result_hashes
    ):
        restored["result_hash"] = qa_result_hashes[old_result_hash]
    return restored


def _restore_generated_page_qa_result_payload(
    session: Session,
    record: dict[str, Any],
    *,
    website_ids: dict[int, int],
    site_plan_ids: dict[int, int],
    planned_page_ids: dict[int, int],
    generated_page_ids: dict[int, int],
    generated_page_revision_ids: dict[int, int],
    page_composition_ids: dict[int, int],
    source_compositions: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    """Remap one immutable QA record and re-hash its restored identity."""

    restored = {
        **record,
        "website_id": _mapped_optional_id(
            website_ids,
            record.get("website_id"),
            "generated_page_qa_results.website_id",
        ),
        "site_plan_id": _mapped_optional_id(
            site_plan_ids,
            record.get("site_plan_id"),
            "generated_page_qa_results.site_plan_id",
        ),
        "planned_page_id": _mapped_optional_id(
            planned_page_ids,
            record.get("planned_page_id"),
            "generated_page_qa_results.planned_page_id",
        ),
        "generated_page_id": _mapped_id(
            generated_page_ids,
            record.get("generated_page_id"),
            "generated_page_qa_results.generated_page_id",
        ),
        "latest_generated_page_revision_id": _mapped_optional_id(
            generated_page_revision_ids,
            record.get("latest_generated_page_revision_id"),
            "generated_page_qa_results.latest_generated_page_revision_id",
        ),
        "page_composition_id": _mapped_optional_id(
            page_composition_ids,
            record.get("page_composition_id"),
            "generated_page_qa_results.page_composition_id",
        ),
        "supersedes_qa_result_id": None,
        "evaluated_at": (
            _datetime_value(
                record["evaluated_at"],
                "generated_page_qa_results.evaluated_at",
            )
            if record.get("evaluated_at") is not None
            else None
        ),
        "created_at": _datetime_value(
            record["created_at"],
            "generated_page_qa_results.created_at",
        ),
        "updated_at": _datetime_value(
            record["updated_at"],
            "generated_page_qa_results.updated_at",
        ),
    }

    old_composition_id = record.get("page_composition_id")
    if isinstance(old_composition_id, int):
        source_composition = source_compositions[old_composition_id]
        restored_composition = session.get(
            PageComposition,
            restored["page_composition_id"],
        )
        if restored_composition is None:
            raise BackupValidationError(
                "Backup QA result composition could not be restored."
            )
        # A QA result bound to the exported current composition can follow the
        # composition's deterministic ID-remap hash. An already-stale historical
        # binding remains unchanged and therefore remains stale after restore.
        if (
            record.get("composition_version")
            == source_composition.get("composition_version")
            and record.get("composition_source_hash")
            == source_composition.get("source_hash")
        ):
            restored["composition_version"] = (
                restored_composition.composition_version
            )
            restored["composition_source_hash"] = restored_composition.source_hash

    if restored.get("lifecycle_status") == "historical_unbound":
        restored["result_hash"] = historical_qa_payload_hash(
            restored["historical_payload"]
        )
    else:
        restored["result_hash"] = qa_result_record_hash(restored)
    return restored


def _canonical_qa_timestamp(value: datetime) -> str:
    normalized = (
        value.replace(tzinfo=UTC)
        if value.tzinfo is None
        else value.astimezone(UTC)
    )
    return normalized.isoformat().replace("+00:00", "Z")


def _qa_hash_values_from_projection(
    projection: dict[str, Any],
    *,
    evaluated_at: datetime,
) -> dict[str, Any]:
    return {
        "website_id": projection.get("website_id"),
        "site_plan_id": projection.get("site_plan_id"),
        "planned_page_id": projection.get("planned_page_id"),
        "generated_page_id": projection.get("page_id"),
        "latest_generated_page_revision_id": projection.get(
            "latest_generated_page_revision_id"
        ),
        "content_hash": projection.get("content_hash"),
        "source_hash": projection.get("source_hash"),
        "page_composition_id": projection.get("page_composition_id"),
        "composition_version": projection.get("composition_version"),
        "composition_source_hash": projection.get("composition_source_hash"),
        "qa_algorithm_key": projection.get("qa_algorithm_key"),
        "qa_algorithm_version": projection.get("qa_algorithm_version"),
        "qa_ruleset_key": projection.get("qa_ruleset_key"),
        "qa_ruleset_version": projection.get("qa_ruleset_version"),
        "qa_ruleset_hash": projection.get("qa_ruleset_hash"),
        "readiness_status": projection.get("readiness_status"),
        "passed_count": projection.get("passed_count"),
        "warning_count": projection.get("warning_count"),
        "failed_count": projection.get("failed_count"),
        "check_payload": projection.get("checks"),
        "evaluated_at": evaluated_at,
    }


def _rehash_restored_candidate_qa_projection(
    session: Session,
    source: dict[str, Any],
    restored: dict[str, Any],
    *,
    source_compositions: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    old_composition_id = source.get("page_composition_id")
    if isinstance(old_composition_id, int):
        source_composition = source_compositions[old_composition_id]
        restored_composition = session.get(
            PageComposition,
            restored.get("page_composition_id"),
        )
        if restored_composition is None:
            raise BackupValidationError(
                "Backup candidate QA composition could not be restored."
            )
        if (
            source.get("composition_version")
            == source_composition.get("composition_version")
            and source.get("composition_source_hash")
            == source_composition.get("source_hash")
        ):
            restored["composition_source_hash"] = restored_composition.source_hash
    evaluated_at = _datetime_value(
        restored.get("checked_at"),
        "approval_audits.qa_result_snapshot.checked_at",
    )
    restored["checked_at"] = _canonical_qa_timestamp(evaluated_at)
    restored["result_hash"] = qa_result_record_hash(
        _qa_hash_values_from_projection(restored, evaluated_at=evaluated_at)
    )
    return restored


def _datetime_value(value: Any, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError as exc:
            raise BackupValidationError(f"Backup contains an invalid timestamp in {field}.") from exc
    raise BackupValidationError(f"Backup contains an invalid timestamp in {field}.")


def _comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _require_backup_timestamp_order(
    earlier: Any,
    later: Any,
    message: str,
) -> None:
    if earlier is None or later is None:
        raise BackupValidationError(message)
    if _comparable_datetime(
        _datetime_value(later, "durable Theme lifecycle timestamp")
    ) < _comparable_datetime(
        _datetime_value(earlier, "durable Theme lifecycle timestamp")
    ):
        raise BackupValidationError(message)


def _require_backup_stored_text(
    value: Any,
    label: str,
    maximum_length: int,
) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > maximum_length
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise BackupValidationError(
            f"{label} must be non-empty bounded text without control characters."
        )


def _validate_site_connection_decision_provenance(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    if backup_version in {"0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        _validate_052_site_connection_provenance_fields(data)

    planning_by_plan = {
        record.get("site_plan_id"): record
        for record in data["site_connection_planning_records"]
    }
    sets_by_id = {record.get("id"): record for record in data["navigation_sets"]}
    items_by_id = {record.get("id"): record for record in data["navigation_items"]}
    plans_by_id = {record.get("id"): record for record in data["site_plans"]}
    pages_by_id = {record.get("id"): record for record in data["planned_pages"]}

    for record in data["site_connection_planning_records"]:
        plan = plans_by_id.get(record.get("site_plan_id"))
        if not plan or record.get("website_id") != plan.get("website_id"):
            raise BackupValidationError(
                "Backup Site Connection planning record crosses a Website or Site Plan boundary."
            )
    for record in data["navigation_sets"]:
        plan = plans_by_id.get(record.get("site_plan_id"))
        if not plan or record.get("website_id") != plan.get("website_id"):
            raise BackupValidationError(
                "Backup Navigation Set crosses a Website or Site Plan boundary."
            )
    for record in data["navigation_items"]:
        plan = plans_by_id.get(record.get("site_plan_id"))
        navigation_set = sets_by_id.get(record.get("navigation_set_id"))
        target = pages_by_id.get(record.get("target_planned_page_id"))
        parent_id = record.get("parent_navigation_item_id")
        parent = items_by_id.get(parent_id) if parent_id is not None else None
        if (
            not plan
            or not navigation_set
            or not target
            or record.get("website_id") != plan.get("website_id")
            or navigation_set.get("website_id") != record.get("website_id")
            or navigation_set.get("site_plan_id") != record.get("site_plan_id")
            or target.get("website_id") != record.get("website_id")
            or target.get("site_plan_id") != record.get("site_plan_id")
            or (
                parent_id is not None
                and (
                    not parent
                    or parent.get("website_id") != record.get("website_id")
                    or parent.get("site_plan_id") != record.get("site_plan_id")
                    or parent.get("navigation_set_id")
                    != record.get("navigation_set_id")
                )
            )
        ):
            raise BackupValidationError(
                "Backup Navigation Item crosses a Website, Site Plan, set, or page boundary."
            )
    for record in data["internal_link_intents"]:
        plan = plans_by_id.get(record.get("site_plan_id"))
        source = pages_by_id.get(record.get("source_planned_page_id"))
        target = pages_by_id.get(record.get("target_planned_page_id"))
        if (
            not plan
            or not source
            or not target
            or record.get("website_id") != plan.get("website_id")
            or source.get("website_id") != record.get("website_id")
            or target.get("website_id") != record.get("website_id")
            or source.get("site_plan_id") != record.get("site_plan_id")
            or target.get("site_plan_id") != record.get("site_plan_id")
        ):
            raise BackupValidationError(
                "Backup Internal Link Intent crosses a Website, Site Plan, or page boundary."
            )

    if backup_version not in {"0.52", "0.53", "0.54", "0.55", "0.56", "0.57", "0.58"}:
        return

    _validate_052_composition_connection_bindings(
        data,
        plans_by_id=plans_by_id,
        pages_by_id=pages_by_id,
        sets_by_id=sets_by_id,
        items_by_id=items_by_id,
    )
    _validate_052_site_connection_suggestion_bindings(
        data,
        planning_by_plan=planning_by_plan,
        sets_by_id=sets_by_id,
    )


def _validate_052_composition_connection_bindings(
    data: dict[str, list[dict[str, Any]]],
    *,
    plans_by_id: dict[Any, dict[str, Any]],
    pages_by_id: dict[Any, dict[str, Any]],
    sets_by_id: dict[Any, dict[str, Any]],
    items_by_id: dict[Any, dict[str, Any]],
) -> None:
    links_by_id = {
        record.get("id"): record for record in data["internal_link_intents"]
    }
    generated_by_id = {
        record.get("id"): record for record in data["generated_pages"]
    }
    authoritative_plan_ids = _authoritative_backup_connection_plan_ids(data)

    def require_page_scope(
        page_id: Any,
        *,
        website_id: Any,
        site_plan_id: Any,
        field: str,
    ) -> dict[str, Any]:
        page = pages_by_id.get(page_id)
        if (
            not page
            or page.get("website_id") != website_id
            or page.get("site_plan_id") != site_plan_id
        ):
            raise BackupValidationError(
                f"Backup Page Composition contains an out-of-scope {field} binding."
            )
        return page

    for composition in data["page_compositions"]:
        website_id = composition.get("website_id")
        site_plan_id = composition.get("site_plan_id")
        plan = plans_by_id.get(site_plan_id)
        planned = require_page_scope(
            composition.get("planned_page_id"),
            website_id=website_id,
            site_plan_id=site_plan_id,
            field="Planned Page",
        )
        generated = generated_by_id.get(composition.get("generated_page_id"))
        if (
            not plan
            or plan.get("website_id") != website_id
            or not generated
            or generated.get("website_id") != website_id
            or planned.get("generated_page_id") != composition.get("generated_page_id")
        ):
            raise BackupValidationError(
                "Backup Page Composition crosses its Website, Site Plan, Planned Page, or draft boundary."
            )

        # A 0.52 backup can be exported immediately after migration 0040 while
        # existing compositions still contain the legacy connection snapshot.
        # Such a graph has draft/legacy decisions and is restored explicitly
        # stale. Only a composition that claims to be current against a fully
        # provenance-complete, active graph may claim the strict nested schema.
        if (
            composition.get("status") != "current"
            or site_plan_id not in authoritative_plan_ids
        ):
            continue

        for component in composition.get("generated_components", []):
            if not isinstance(component, dict):
                raise BackupValidationError(
                    "Backup Page Composition contains an invalid generated component."
                )
            bindings = component.get("input_bindings", {})
            if not isinstance(bindings, dict):
                raise BackupValidationError(
                    "Backup Page Composition component bindings must be an object."
                )
            navigation_set_id = bindings.get("navigation_set_id")
            if navigation_set_id is not None:
                navigation_set = sets_by_id.get(navigation_set_id)
                if (
                    not navigation_set
                    or navigation_set.get("website_id") != website_id
                    or navigation_set.get("site_plan_id") != site_plan_id
                ):
                    raise BackupValidationError(
                        "Backup Page Composition Navigation Set binding is out of scope."
                    )
            for link_id in bindings.get("internal_link_intent_ids", []):
                link = links_by_id.get(link_id)
                if (
                    not link
                    or link.get("website_id") != website_id
                    or link.get("site_plan_id") != site_plan_id
                    or link.get("source_planned_page_id") != planned.get("id")
                ):
                    raise BackupValidationError(
                        "Backup Page Composition Internal Link binding is out of scope."
                    )
            for page_id in bindings.get("draft_related_page_ids", []):
                require_page_scope(
                    page_id,
                    website_id=website_id,
                    site_plan_id=site_plan_id,
                    field="related Planned Page",
                )

        snapshot = composition.get("source_snapshot", {})
        if not isinstance(snapshot, dict):
            raise BackupValidationError(
                "Backup Page Composition source snapshot must be an object."
            )
        if (
            snapshot.get("website_id") != website_id
            or snapshot.get("site_plan_id") != site_plan_id
            or snapshot.get("planned_page_id") != planned.get("id")
            or snapshot.get("generated_page_id") != generated.get("id")
        ):
            raise BackupValidationError(
                "Backup Page Composition source identity is out of scope."
            )
        snapshot_contracts = (
            (
                "navigation_sets",
                sorted(
                    record_id
                    for record_id, record in sets_by_id.items()
                    if record.get("website_id") == website_id
                    and record.get("site_plan_id") == site_plan_id
                ),
            ),
            (
                "navigation_items",
                sorted(
                    record_id
                    for record_id, record in items_by_id.items()
                    if record.get("website_id") == website_id
                    and record.get("site_plan_id") == site_plan_id
                    and record.get("status") == "active"
                ),
            ),
            (
                "internal_links",
                sorted(
                    record_id
                    for record_id, record in links_by_id.items()
                    if record.get("website_id") == website_id
                    and record.get("site_plan_id") == site_plan_id
                    and record.get("source_planned_page_id") == planned.get("id")
                    and record.get("approval_state") == "approved"
                ),
            ),
        )
        for field, expected_ids in snapshot_contracts:
            values = snapshot.get(field)
            if not isinstance(values, list) or any(
                not isinstance(value, dict)
                or type(value.get("id")) is not int
                for value in values
            ):
                raise BackupValidationError(
                    f"Backup Page Composition {field} snapshot is malformed."
                )
            observed_ids = [value["id"] for value in values]
            if observed_ids != expected_ids:
                raise BackupValidationError(
                    f"Backup Page Composition {field} snapshot is incomplete, duplicated, or out of order."
                )
        for value in snapshot.get("navigation_sets", []):
            navigation_set = sets_by_id.get(value.get("id")) if isinstance(value, dict) else None
            if (
                not navigation_set
                or navigation_set.get("website_id") != website_id
                or navigation_set.get("site_plan_id") != site_plan_id
            ):
                raise BackupValidationError(
                    "Backup Page Composition Navigation Set snapshot is out of scope."
                )
        for value in snapshot.get("navigation_items", []):
            item = items_by_id.get(value.get("id")) if isinstance(value, dict) else None
            target = value.get("target") if isinstance(value, dict) else None
            if (
                not item
                or item.get("website_id") != website_id
                or item.get("site_plan_id") != site_plan_id
                or not isinstance(target, dict)
                or target.get("planned_page_id") != item.get("target_planned_page_id")
            ):
                raise BackupValidationError(
                    "Backup Page Composition Navigation Item snapshot is out of scope."
                )
            require_page_scope(
                target.get("planned_page_id"),
                website_id=website_id,
                site_plan_id=site_plan_id,
                field="Navigation target",
            )
        for value in snapshot.get("internal_links", []):
            link = links_by_id.get(value.get("id")) if isinstance(value, dict) else None
            target = value.get("target") if isinstance(value, dict) else None
            if (
                not link
                or link.get("website_id") != website_id
                or link.get("site_plan_id") != site_plan_id
                or link.get("source_planned_page_id") != planned.get("id")
                or not isinstance(target, dict)
                or target.get("planned_page_id") != link.get("target_planned_page_id")
            ):
                raise BackupValidationError(
                    "Backup Page Composition Internal Link snapshot is out of scope."
                )
            require_page_scope(
                target.get("planned_page_id"),
                website_id=website_id,
                site_plan_id=site_plan_id,
                field="Internal Link target",
            )


def _authoritative_backup_connection_plan_ids(
    data: dict[str, list[dict[str, Any]]],
) -> set[Any]:
    """Return plans whose complete operator graph may back a current snapshot."""

    def complete(record: dict[str, Any]) -> bool:
        return (
            isinstance(record.get("rationale"), str)
            and bool(record["rationale"].strip())
            and isinstance(record.get("decided_by"), str)
            and bool(record["decided_by"].strip())
            and type(record.get("decision_version")) is int
            and record["decision_version"] >= 1
            and record.get("decided_at") is not None
        )

    plans: set[Any] = set()
    plan_ids = {record.get("id") for record in data["site_plans"]}
    for plan_id in plan_ids:
        navigation_sets = [
            record
            for record in data["navigation_sets"]
            if record.get("site_plan_id") == plan_id
        ]
        navigation_items = [
            record
            for record in data["navigation_items"]
            if record.get("site_plan_id") == plan_id
        ]
        internal_links = [
            record
            for record in data["internal_link_intents"]
            if record.get("site_plan_id") == plan_id
        ]
        if (
            {record.get("set_type") for record in navigation_sets}
            != {"primary", "utility", "footer"}
            or any(
                record.get("status") != "active" or not complete(record)
                for record in navigation_sets
            )
            or any(not complete(record) for record in navigation_items)
            or any(not complete(record) for record in internal_links)
        ):
            continue
        active_item_set_ids = {
            record.get("navigation_set_id")
            for record in navigation_items
            if record.get("status") == "active"
        }
        if all(record.get("id") in active_item_set_ids for record in navigation_sets):
            plans.add(plan_id)
    return plans


def _validate_052_site_connection_provenance_fields(
    data: dict[str, list[dict[str, Any]]],
) -> None:
    provenance_fields = {
        "rationale",
        "decided_by",
        "decision_version",
        "decided_at",
        "source_suggestion_key",
    }
    group_statuses = {
        "navigation_sets": ("status", {"draft", "active", "disabled"}),
        "navigation_items": ("status", {"draft", "active", "disabled"}),
        "internal_link_intents": (
            "approval_state",
            {"proposed", "approved", "rejected"},
        ),
    }
    for group, (status_field, valid_statuses) in group_statuses.items():
        for record in data[group]:
            if not provenance_fields.issubset(record):
                raise BackupValidationError(
                    f"Backup 0.52 '{group}' record omits decision provenance fields."
                )
            if record.get(status_field) not in valid_statuses:
                raise BackupValidationError(
                    f"Backup contains an invalid decision state in '{group}'."
                )
            core_values = (
                record.get("rationale"),
                record.get("decided_by"),
                record.get("decision_version"),
                record.get("decided_at"),
            )
            if all(value is None for value in core_values):
                if record.get("source_suggestion_key") is not None:
                    raise BackupValidationError(
                        f"Backup contains suggestion provenance without an operator decision in '{group}'."
                    )
                continue
            if any(value is None for value in core_values):
                raise BackupValidationError(
                    f"Backup contains partial decision provenance in '{group}'."
                )
            if (
                not isinstance(record["rationale"], str)
                or not record["rationale"].strip()
                or not isinstance(record["decided_by"], str)
                or not record["decided_by"].strip()
                or type(record["decision_version"]) is not int
                or record["decision_version"] < 1
            ):
                raise BackupValidationError(
                    f"Backup contains invalid decision provenance in '{group}'."
                )
            _datetime_value(record["decided_at"], f"{group}.decided_at")
            source_key = record.get("source_suggestion_key")
            if group == "navigation_sets" and source_key is not None:
                raise BackupValidationError(
                    "Backup Navigation Set cannot reference an item-level Atlas suggestion."
                )
            if source_key is not None and (
                not isinstance(source_key, str)
                or not source_key.strip()
                or len(source_key) > 200
            ):
                raise BackupValidationError(
                    f"Backup contains invalid suggestion provenance in '{group}'."
                )


def _validate_052_site_connection_suggestion_bindings(
    data: dict[str, list[dict[str, Any]]],
    *,
    planning_by_plan: dict[Any, dict[str, Any]],
    sets_by_id: dict[Any, dict[str, Any]],
) -> None:

    def suggestion(record: dict[str, Any], group: str) -> dict[str, Any] | None:
        source_key = record.get("source_suggestion_key")
        if source_key is None:
            return None
        planning = planning_by_plan.get(record.get("site_plan_id"))
        if not planning:
            raise BackupValidationError(
                f"Backup '{group}' suggestion provenance has no planning record."
            )
        field = (
            "generated_navigation_suggestions"
            if group != "internal_link_intents"
            else "generated_internal_link_suggestions"
        )
        candidates = planning.get(field)
        if not isinstance(candidates, list):
            raise BackupValidationError(
                f"Backup '{group}' suggestion source is not a list."
            )
        match = next(
            (
                item
                for item in candidates
                if isinstance(item, dict)
                and item.get("suggestion_key") == source_key
            ),
            None,
        )
        if match is None:
            raise BackupValidationError(
                f"Backup '{group}' references an unknown or stale suggestion."
            )
        return match

    for record in data["navigation_items"]:
        match = suggestion(record, "navigation_items")
        if match is None:
            continue
        navigation_set = sets_by_id.get(record.get("navigation_set_id"))
        if (
            not navigation_set
            or match.get("set_type") != navigation_set.get("set_type")
            or match.get("target_planned_page_id")
            != record.get("target_planned_page_id")
        ):
            raise BackupValidationError(
                "Backup Navigation Item suggestion provenance does not match its decision identity."
            )
    for record in data["internal_link_intents"]:
        match = suggestion(record, "internal_link_intents")
        if match is not None and (
            match.get("source_planned_page_id")
            != record.get("source_planned_page_id")
            or match.get("target_planned_page_id")
            != record.get("target_planned_page_id")
            or match.get("relationship_type") != record.get("relationship_type")
        ):
            raise BackupValidationError(
                "Backup Internal Link suggestion provenance does not match its decision identity."
            )


def _validate_nested_qa_page_identities(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    """Reject QA projections that claim a page other than their owner."""

    require_identity = backup_version in {"0.55", "0.56", "0.57", "0.58"}
    for record in data["generated_pages"]:
        qa_result = record.get("qa_result")
        if qa_result is None:
            continue
        if not isinstance(qa_result, dict):
            raise BackupValidationError(
                "Backup Generated Page QA result must be an object."
            )
        if not require_identity:
            _validate_legacy_qa_projection(
                qa_result,
                field="generated_pages.qa_result",
            )
            continue
        page_id = qa_result.get("page_id")
        if require_identity and page_id != record.get("id"):
            raise BackupValidationError(
                "Backup Generated Page QA result does not match its enclosing page identity."
            )

    for record in data["approval_audits"]:
        snapshot = record.get("qa_result_snapshot")
        if not isinstance(snapshot, dict):
            raise BackupValidationError(
                "Backup Approval Audit QA result snapshot must be an object."
            )
        if not require_identity:
            _validate_legacy_qa_projection(
                snapshot,
                field="approval_audits.qa_result_snapshot",
            )
            continue
        page_id = snapshot.get("page_id")
        # Approval snapshots are immutable historical evidence. Exact legacy
        # snapshots may truthfully preserve a pre-binding restore defect; full
        # candidate and durable snapshots still carry authoritative page identity.
        if (
            require_identity
            and (
                snapshot.get("qa_result_id") is not None
                or snapshot.get("lifecycle_status") == "candidate"
            )
            and page_id != record.get("generated_page_id")
        ):
            raise BackupValidationError(
                "Backup Approval Audit QA result snapshot does not match its page identity."
            )


def _validate_theme_configuration_graph(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    groups = (
        "theme_families",
        "theme_family_versions",
        "website_theme_configurations",
        "website_theme_component_configurations",
        "theme_configuration_audits",
    )
    if backup_version not in {"0.57", "0.58"}:
        if any(data[group] for group in groups):
            raise BackupValidationError(
                "Legacy backup contains unsupported durable Theme configuration records."
            )
        return

    from app.schemas.theme_families import (
        CompactEstimateFormConfiguration,
        PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS,
        PERFORMANCE_LOCAL_V2_SOURCE_COMMIT,
        PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS,
        ThemeConfigurationAuditRead,
        ThemeFamilyCreate,
        ThemeFamilyRead,
        ThemeFamilyVersionCreate,
        ThemeFamilyVersionRead,
        WebsiteThemeComponentConfigurationCreate,
        WebsiteThemeComponentConfigurationRead,
        WebsiteThemeConfigurationCreate,
        WebsiteThemeConfigurationRead,
        validate_component_payload,
        validate_component_schedule,
    )
    from app.services.form_submission_contracts import (
        validate_provider_disabled_form,
    )
    from app.schemas.themes import ThemeDesignTokens
    from app.services.themes import validate_theme_accessibility

    def indexed(group: str) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        for record in data[group]:
            record_id = _record_id(record, group)
            if record_id in result:
                raise BackupValidationError(
                    f"Backup contains duplicate ids in '{group}'."
                )
            result[record_id] = record
        return result

    families = indexed("theme_families")
    versions = indexed("theme_family_versions")
    configurations = indexed("website_theme_configurations")
    components = indexed("website_theme_component_configurations")
    audits = indexed("theme_configuration_audits")
    businesses = indexed("businesses")
    websites = indexed("websites")
    planned_pages = indexed("planned_pages")
    themes = indexed("themes")
    selections = indexed("website_theme_selections")

    try:
        for record in families.values():
            ThemeFamilyRead.model_validate(record)
            ThemeFamilyCreate.model_validate(
                {
                    field: record.get(field)
                    for field in (
                        "family_key",
                        "display_name",
                        "description",
                        "provider_source_identity",
                        "created_by",
                    )
                }
            )
            lifecycle_status = record.get("lifecycle_status")
            retired_by = record.get("retired_by")
            retired_at = record.get("retired_at")
            retirement_complete = (
                isinstance(retired_by, str)
                and bool(retired_by.strip())
                and retired_at is not None
            )
            if retired_at is not None:
                _datetime_value(retired_at, "theme_families.retired_at")
            _require_backup_timestamp_order(
                record.get("created_at"),
                record.get("updated_at"),
                "Theme Family update precedes its creation.",
            )
            if retired_at is not None:
                _require_backup_timestamp_order(
                    record.get("created_at"),
                    retired_at,
                    "Theme Family retirement precedes its creation.",
                )
            if (
                (lifecycle_status == "registered" and (retired_by is not None or retired_at is not None))
                or (lifecycle_status == "retired" and not retirement_complete)
                or record.get("integrity_fingerprint")
                != _canonical_json_hash(
                    _theme_family_fingerprint_payload(record)
                )
            ):
                raise BackupValidationError(
                    "Backup contains an invalid Theme Family lifecycle or fingerprint."
                )

        compatibility_identities: set[str] = set()
        family_version_predecessors: set[int] = set()
        for record in versions.values():
            ThemeFamilyVersionRead.model_validate(record)
            version_create_shape = {
                    field: record.get(field)
                    for field in (
                        "version",
                        "lifecycle_status",
                        "production_ready",
                        "source_commit",
                        "supported_component_contracts",
                        "created_by",
                        "supersedes_theme_family_version_id",
                    )
                }
            version_create_shape["lifecycle_status"] = "preview_candidate"
            version_create_shape["production_ready"] = False
            ThemeFamilyVersionCreate.model_validate(version_create_shape)
            family = families.get(record.get("theme_family_id"))
            if family is None:
                raise BackupValidationError(
                    "Theme Family Version references a missing Theme Family."
                )
            contracts = record.get("supported_component_contracts")
            if (
                family.get("family_key") == "performance-local"
                and record.get("version") == 2
                and (
                    contracts != list(PERFORMANCE_LOCAL_V2_COMPONENT_CONTRACTS)
                    or record.get("source_commit")
                    != PERFORMANCE_LOCAL_V2_SOURCE_COMMIT
                )
            ):
                raise BackupValidationError(
                    "Performance Local v2 backup source commit or contract is not canonical."
                )
            if (
                family.get("family_key") == "performance-local"
                and record.get("version") == 3
                and contracts != list(PERFORMANCE_LOCAL_V3_COMPONENT_CONTRACTS)
            ):
                raise BackupValidationError(
                    "Performance Local v3 backup contract is not canonical."
                )
            compatibility = _canonical_json_hash(
                {
                    "family_key": family.get("family_key"),
                    "version": record.get("version"),
                    "supported_component_contracts": contracts,
                }
            )
            lifecycle_status = record.get("lifecycle_status")
            retired_by = record.get("retired_by")
            retired_at = record.get("retired_at")
            retirement_complete = (
                isinstance(retired_by, str)
                and bool(retired_by.strip())
                and retired_at is not None
            )
            if retired_at is not None:
                _datetime_value(
                    retired_at,
                    "theme_family_versions.retired_at",
                )
            _require_backup_timestamp_order(
                record.get("created_at"),
                record.get("updated_at"),
                "Theme Version update precedes its creation.",
            )
            if retired_at is not None:
                _require_backup_timestamp_order(
                    record.get("created_at"),
                    retired_at,
                    "Theme Version retirement precedes its creation.",
                )
            if (
                (lifecycle_status != "retired" and (retired_by is not None or retired_at is not None))
                or (lifecycle_status == "retired" and not retirement_complete)
                or (
                    record.get("production_ready") is True
                    and lifecycle_status != "approved"
                )
                or record.get("compatibility_identity") != compatibility
                or compatibility in compatibility_identities
                or record.get("integrity_fingerprint")
                != _canonical_json_hash(
                    _theme_family_version_fingerprint_payload(record)
                )
            ):
                raise BackupValidationError(
                    "Backup contains an invalid Theme Family Version lifecycle or identity."
                )
            compatibility_identities.add(compatibility)
            predecessor_id = record.get("supersedes_theme_family_version_id")
            if (
                family.get("family_key") == "performance-local"
                and record.get("version") == 3
                and predecessor_id is None
            ):
                raise BackupValidationError(
                    "Performance Local v3 backup requires its exact v2 predecessor."
                )
            if predecessor_id is not None:
                if predecessor_id in family_version_predecessors:
                    raise BackupValidationError(
                        "Theme Family Version predecessor has multiple successors."
                    )
                family_version_predecessors.add(predecessor_id)
                predecessor = versions.get(predecessor_id)
                if (
                    predecessor is None
                    or predecessor.get("theme_family_id")
                    != record.get("theme_family_id")
                    or not isinstance(predecessor.get("version"), int)
                    or predecessor["version"] >= record.get("version", 0)
                ):
                    raise BackupValidationError(
                        "Theme Family Version lineage is inconsistent."
                    )
                if (
                    family.get("family_key") == "performance-local"
                    and record.get("version") == 3
                    and predecessor.get("version") != 2
                ):
                    raise BackupValidationError(
                        "Performance Local v3 backup must supersede its exact v2 predecessor."
                    )
                _require_backup_timestamp_order(
                    predecessor.get("updated_at"),
                    record.get("created_at"),
                    "Theme Version successor predates predecessor transition.",
                )

        current_configuration_scopes: set[tuple[Any, ...]] = set()
        configuration_predecessors: set[int] = set()
        for record in configurations.values():
            WebsiteThemeConfigurationRead.model_validate(record)
            WebsiteThemeConfigurationCreate.model_validate(
                {
                    field: record.get(field)
                    for field in (
                        "theme_family_version_id",
                        "configuration_key",
                        "created_by",
                        "creation_rationale",
                        "supersedes_configuration_id",
                    )
                }
            )
            _require_backup_stored_text(
                record.get("updated_by"),
                "Website Theme configuration updater",
                160,
            )
            website = websites.get(record.get("website_id"))
            if (
                website is None
                or record.get("business_id") != website.get("business_id")
                or record.get("business_id") not in businesses
                or record.get("theme_family_version_id") not in versions
            ):
                raise BackupValidationError(
                    "Website Theme configuration crosses its ownership boundary."
                )
            paired_fields = (
                ("approved_by", "approved_at"),
                ("activated_by", "activated_at"),
                ("rollback_by", "rollback_at"),
            )
            for actor_field, timestamp_field in paired_fields:
                actor = record.get(actor_field)
                timestamp = record.get(timestamp_field)
                if (actor is None) != (timestamp is None):
                    raise BackupValidationError(
                        "Website Theme configuration lifecycle evidence is incomplete."
                    )
                if actor is not None and (
                    not isinstance(actor, str) or not actor.strip()
                ):
                    raise BackupValidationError(
                        "Website Theme configuration lifecycle actor is invalid."
                    )
                if timestamp is not None:
                    _datetime_value(
                        timestamp,
                        f"website_theme_configurations.{timestamp_field}",
                    )
            materialized_theme_id = record.get("materialized_theme_id")
            selection_id = record.get("website_theme_selection_id")
            if (materialized_theme_id is None) != (selection_id is None):
                raise BackupValidationError(
                    "Website Theme configuration Theme-selection identity is incomplete."
                )
            if materialized_theme_id is not None:
                theme = themes.get(materialized_theme_id)
                selection = selections.get(selection_id)
                version = versions.get(record.get("theme_family_version_id"))
                family = (
                    families.get(version.get("theme_family_id"))
                    if version is not None
                    else None
                )
                if (
                    theme is None
                    or selection is None
                    or family is None
                    or theme.get("website_id") != record.get("website_id")
                    or theme.get("business_id") != record.get("business_id")
                    or theme.get("brand_id") != website.get("brand_id")
                    or theme.get("theme_key") != family.get("family_key")
                    or selection.get("website_id") != record.get("website_id")
                    or selection.get("theme_id") != materialized_theme_id
                ):
                    raise BackupValidationError(
                        "Website Theme configuration crosses its exact governed Theme-selection identity."
                    )
            lifecycle_status = record.get("lifecycle_status")
            lifecycle_evidence = (
                "approved_by",
                "activated_by",
                "rollback_by",
                "materialized_theme_id",
                "website_theme_selection_id",
            )
            if lifecycle_status == "draft" and any(
                record.get(field) is not None for field in lifecycle_evidence
            ):
                raise BackupValidationError(
                    "Draft Website Theme configuration contains later lifecycle evidence."
                )
            if lifecycle_status == "approved" and (
                record.get("approved_by") is None
                or any(
                    record.get(field) is not None
                    for field in (
                        "activated_by",
                        "rollback_by",
                        "materialized_theme_id",
                        "website_theme_selection_id",
                    )
                )
            ):
                raise BackupValidationError(
                    "Approved Website Theme configuration has invalid lifecycle evidence."
                )
            if lifecycle_status == "active":
                theme = themes.get(materialized_theme_id)
                selection = selections.get(selection_id)
                version = versions.get(record.get("theme_family_version_id"))
                if (
                    record.get("approved_by") is None
                    or record.get("activated_by") is None
                    or record.get("rollback_by") is not None
                    or theme is None
                    or selection is None
                    or version is None
                    or version.get("lifecycle_status") != "approved"
                    or version.get("production_ready") is not True
                    or family.get("lifecycle_status") != "registered"
                    or theme.get("lifecycle_status") != "available"
                    or theme.get("approval_status") != "approved"
                    or selection.get("status") != "active"
                    or [
                        candidate.get("id")
                        for candidate in selections.values()
                        if candidate.get("website_id") == record.get("website_id")
                        and candidate.get("status") == "active"
                    ]
                    != [selection_id]
                    or not validate_theme_accessibility(
                        ThemeDesignTokens.model_validate(theme.get("design_tokens"))
                    ).valid
                ):
                    raise BackupValidationError(
                        "Active Website Theme configuration lacks its exact approved active Theme selection."
                    )
            if (
                record.get("rollback_by") is not None
                and record.get("activated_by") is None
            ):
                raise BackupValidationError(
                    "Website Theme configuration rollback lacks activation evidence."
                )
            if (
                record.get("activated_by") is not None
                and record.get("approved_by") is None
            ):
                raise BackupValidationError(
                    "Website Theme configuration activation lacks approval evidence."
                )
            _require_backup_timestamp_order(
                record.get("created_at"),
                record.get("updated_at"),
                "Website Theme configuration update precedes its creation.",
            )
            if record.get("approved_at") is not None:
                _require_backup_timestamp_order(
                    record.get("created_at"),
                    record.get("approved_at"),
                    "Website Theme configuration approval precedes its creation.",
                )
            if record.get("activated_at") is not None:
                _require_backup_timestamp_order(
                    record.get("approved_at"),
                    record.get("activated_at"),
                    "Website Theme configuration activation precedes its approval.",
                )
            if record.get("rollback_at") is not None:
                _require_backup_timestamp_order(
                    record.get("activated_at"),
                    record.get("rollback_at"),
                    "Website Theme configuration rollback precedes its activation.",
                )
            if (
                record.get("integrity_fingerprint")
                != _canonical_json_hash(
                    _website_theme_configuration_fingerprint_payload(record)
                )
            ):
                raise BackupValidationError(
                    "Backup Website Theme configuration fingerprint does not match."
                )
            scope = (
                record.get("website_id"),
                record.get("theme_family_version_id"),
                record.get("configuration_key"),
            )
            if record.get("lifecycle_status") in {"draft", "approved", "active"}:
                if scope in current_configuration_scopes:
                    raise BackupValidationError(
                        "Backup contains multiple current Website Theme configurations for one scope."
                    )
                current_configuration_scopes.add(scope)
            predecessor_id = record.get("supersedes_configuration_id")
            version = record.get("version")
            if (version == 1) != (predecessor_id is None):
                raise BackupValidationError(
                    "Website Theme configuration lineage is incomplete."
                )
            if predecessor_id is not None:
                if predecessor_id in configuration_predecessors:
                    raise BackupValidationError(
                        "Website Theme configuration predecessor has multiple successors."
                    )
                configuration_predecessors.add(predecessor_id)
                predecessor = configurations.get(predecessor_id)
                if (
                    predecessor is None
                    or predecessor.get("website_id") != record.get("website_id")
                    or predecessor.get("theme_family_version_id")
                    != record.get("theme_family_version_id")
                    or predecessor.get("configuration_key")
                    != record.get("configuration_key")
                    or predecessor.get("version", 0) + 1 != version
                ):
                    raise BackupValidationError(
                        "Website Theme configuration lineage is inconsistent."
                    )
                _require_backup_timestamp_order(
                    predecessor.get("updated_at"),
                    record.get("created_at"),
                    "Website Theme configuration successor predates predecessor supersession.",
                )

        for configuration_id, record in configurations.items():
            lifecycle_status = record.get("lifecycle_status")
            if (
                configuration_id in configuration_predecessors
                and lifecycle_status not in {"superseded", "retired"}
            ) or (
                lifecycle_status == "superseded"
                and configuration_id not in configuration_predecessors
            ):
                raise BackupValidationError(
                    "Website Theme configuration lifecycle does not match its lineage."
                )

        current_website_components: set[tuple[Any, ...]] = set()
        current_page_overrides: set[tuple[Any, ...]] = set()
        component_predecessors: set[int] = set()
        for record in components.values():
            WebsiteThemeComponentConfigurationRead.model_validate(record)
            configuration = configurations.get(
                record.get("website_theme_configuration_id")
            )
            family_version = versions.get(record.get("theme_family_version_id"))
            if (
                configuration is None
                or family_version is None
                or record.get("website_id") != configuration.get("website_id")
                or record.get("theme_family_version_id")
                != configuration.get("theme_family_version_id")
            ):
                raise BackupValidationError(
                    "Theme component configuration crosses its governed scope."
                )
            scope_type = record.get("scope_type")
            planned_page_id = record.get("planned_page_id")
            if scope_type == "website_default":
                if (
                    planned_page_id is not None
                    or record.get("overrides_component_configuration_id")
                    is not None
                ):
                    raise BackupValidationError(
                        "Website-default Theme component has a Page override binding."
                    )
            elif scope_type == "page_override":
                page = planned_pages.get(planned_page_id)
                if (
                    page is None
                    or page.get("website_id") != record.get("website_id")
                    or record.get("overrides_component_configuration_id") is None
                ):
                    raise BackupValidationError(
                        "Theme component Page override crosses its Website boundary."
                    )
            else:
                raise BackupValidationError(
                    "Theme component configuration has an invalid scope."
                )
            normalized_payload = validate_component_payload(
                record.get("component_key"),
                record.get("configuration_payload"),
                record.get("component_contract_version"),
            )
            if normalized_payload != record.get("configuration_payload"):
                raise BackupValidationError(
                    "Theme component configuration payload is not canonical."
                )
            effective_at_value = (
                _datetime_value(
                    record.get("effective_at"),
                    "website_theme_component_configurations.effective_at",
                )
                if record.get("effective_at") is not None
                else None
            )
            expires_at_value = (
                _datetime_value(
                    record.get("expires_at"),
                    "website_theme_component_configurations.expires_at",
                )
                if record.get("expires_at") is not None
                else None
            )
            try:
                validate_component_schedule(
                    record.get("component_key"),
                    normalized_payload,
                    effective_at_value,
                    expires_at_value,
                )
            except ValueError as exc:
                raise BackupValidationError(
                    f"Theme component schedule is invalid: {exc}"
                ) from exc
            WebsiteThemeComponentConfigurationCreate.model_validate(
                {
                    field: record.get(field)
                    for field in (
                        "component_instance_key",
                        "component_key",
                        "component_contract_version",
                        "scope_type",
                        "planned_page_id",
                        "enabled",
                        "variant",
                        "placement",
                        "responsive_visibility",
                        "configuration_payload",
                        "effective_at",
                        "expires_at",
                        "approval_identity",
                        "created_by",
                        "destination_component_configuration_id",
                        "overrides_component_configuration_id",
                    )
                }
            )
            _require_backup_stored_text(
                record.get("updated_by"),
                "Theme component updater",
                160,
            )
            approval_identity = record.get("approval_identity")
            if not isinstance(approval_identity, str) or not approval_identity.strip():
                raise BackupValidationError(
                    "Theme component configuration lacks approval identity."
                )
            if (
                record.get("component_key") == "campaign_banner"
                and normalized_payload.get("approval_identity")
                != approval_identity
            ):
                raise BackupValidationError(
                    "Theme campaign approval identity does not match."
                )
            if (
                record.get("component_key") == "compact_estimate_form"
                and record.get("component_contract_version") == 2
            ):
                validate_provider_disabled_form(
                    CompactEstimateFormConfiguration.model_validate(
                        normalized_payload
                    )
                )
            matching_contracts = [
                contract
                for contract in family_version.get(
                    "supported_component_contracts", []
                )
                if contract.get("component_key")
                == record.get("component_key")
            ]
            if len(matching_contracts) != 1:
                raise BackupValidationError(
                    "Theme component lacks one exact Theme Version contract."
                )
            contract = matching_contracts[0]
            if (
                contract.get("contract_version")
                != record.get("component_contract_version")
                or contract.get("placement") != record.get("placement")
                or contract.get("variant") != record.get("variant")
                or contract.get("responsive_visibility")
                != record.get("responsive_visibility")
                or (
                    scope_type == "page_override"
                    and contract.get("supports_page_override") is not True
                )
            ):
                raise BackupValidationError(
                    "Theme component does not match its exact Theme Version contract."
                )
            for identity_field, timestamp_field in (
                ("activation_identity", "activated_at"),
                ("rollback_identity", "rollback_at"),
            ):
                identity = record.get(identity_field)
                timestamp = record.get(timestamp_field)
                if (identity is None) != (timestamp is None):
                    raise BackupValidationError(
                        "Theme component lifecycle evidence is incomplete."
                    )
                if identity is not None and (
                    not isinstance(identity, str) or not identity.strip()
                ):
                    raise BackupValidationError(
                        "Theme component lifecycle identity is invalid."
                    )
                if timestamp is not None:
                    _datetime_value(
                        timestamp,
                        f"website_theme_component_configurations.{timestamp_field}",
                    )
            if (
                record.get("rollback_identity") is not None
                and record.get("activation_identity") is None
            ):
                raise BackupValidationError(
                    "Theme component rollback lacks activation evidence."
                )
            _require_backup_timestamp_order(
                record.get("created_at"),
                record.get("updated_at"),
                "Theme component update precedes its creation.",
            )
            if record.get("activated_at") is not None:
                _require_backup_timestamp_order(
                    record.get("created_at"),
                    record.get("activated_at"),
                    "Theme component activation precedes its creation.",
                )
            if record.get("rollback_at") is not None:
                _require_backup_timestamp_order(
                    record.get("activated_at"),
                    record.get("rollback_at"),
                    "Theme component rollback precedes its activation.",
                )
            effective_at = effective_at_value
            expires_at = expires_at_value
            if (
                effective_at is not None
                and expires_at is not None
                and _comparable_datetime(expires_at)
                < _comparable_datetime(effective_at)
            ):
                raise BackupValidationError(
                    "Theme component expiration precedes its effective time."
                )
            if record.get("integrity_fingerprint") != _canonical_json_hash(
                _theme_component_configuration_fingerprint_payload(record)
            ):
                raise BackupValidationError(
                    "Theme component integrity fingerprint does not match."
                )
            predecessor_id = record.get("supersedes_component_configuration_id")
            revision = record.get("revision")
            if (revision == 1) != (predecessor_id is None):
                raise BackupValidationError(
                    "Theme component revision lineage is incomplete."
                )
            if predecessor_id is not None:
                if predecessor_id in component_predecessors:
                    raise BackupValidationError(
                        "Theme component predecessor has multiple successors."
                    )
                component_predecessors.add(predecessor_id)
                predecessor = components.get(predecessor_id)
                if (
                    predecessor is None
                    or predecessor.get("website_theme_configuration_id")
                    != record.get("website_theme_configuration_id")
                    or predecessor.get("component_instance_key")
                    != record.get("component_instance_key")
                    or predecessor.get("revision", 0) + 1 != revision
                ):
                    raise BackupValidationError(
                        "Theme component revision lineage is inconsistent."
                    )
                _require_backup_timestamp_order(
                    predecessor.get("updated_at"),
                    record.get("created_at"),
                    "Theme component successor predates predecessor supersession.",
                )
            destination_id = record.get(
                "destination_component_configuration_id"
            )
            requires_destination = record.get("component_key") in {
                "campaign_banner",
                "sticky_mobile_action_bar",
            }
            if requires_destination != (destination_id is not None):
                raise BackupValidationError(
                    "Theme conversion action has an invalid destination binding."
                )
            if destination_id is not None:
                destination = components.get(destination_id)
                if (
                    destination is None
                    or destination.get("website_theme_configuration_id")
                    != record.get("website_theme_configuration_id")
                    or destination.get("website_id") != record.get("website_id")
                    or destination.get("theme_family_version_id")
                    != record.get("theme_family_version_id")
                    or destination.get("component_key")
                    != "compact_estimate_form"
                    or (
                        record.get("lifecycle_status") == "current"
                        and destination.get("lifecycle_status") != "current"
                    )
                    or destination.get("lifecycle_status")
                    not in {"current", "superseded"}
                    or destination.get("enabled") is not True
                ):
                    raise BackupValidationError(
                        "Theme conversion destination is not the exact current compact form."
                    )
            override_id = record.get("overrides_component_configuration_id")
            if override_id is not None:
                target = components.get(override_id)
                if (
                    target is None
                    or target.get("website_theme_configuration_id")
                    != record.get("website_theme_configuration_id")
                    or target.get("website_id") != record.get("website_id")
                    or target.get("theme_family_version_id")
                    != record.get("theme_family_version_id")
                    or target.get("scope_type") != "website_default"
                    or (
                        record.get("lifecycle_status") == "current"
                        and target.get("lifecycle_status") != "current"
                    )
                    or target.get("lifecycle_status")
                    not in {"current", "superseded"}
                    or target.get("component_key")
                    != record.get("component_key")
                    or target.get("component_contract_version")
                    != record.get("component_contract_version")
                ):
                    raise BackupValidationError(
                        "Theme Page override does not bind the exact Website-default component."
                    )
            if record.get("lifecycle_status") == "current":
                if scope_type == "website_default":
                    key = (
                        record.get("website_theme_configuration_id"),
                        record.get("component_instance_key"),
                    )
                    if key in current_website_components:
                        raise BackupValidationError(
                            "Backup contains duplicate current Website Theme components."
                        )
                    current_website_components.add(key)
                else:
                    key = (
                        record.get("website_theme_configuration_id"),
                        planned_page_id,
                        override_id,
                    )
                    if key in current_page_overrides:
                        raise BackupValidationError(
                            "Backup contains duplicate current Theme Page overrides."
                        )
                    current_page_overrides.add(key)

        for component_id, record in components.items():
            lifecycle_status = record.get("lifecycle_status")
            if (
                component_id in component_predecessors
                and lifecycle_status != "superseded"
            ) or (
                lifecycle_status == "superseded"
                and component_id not in component_predecessors
            ):
                raise BackupValidationError(
                    "Theme component lifecycle does not match its revision lineage."
                )

        def required_audit_actions(
            target_field: str,
            target: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any]]:
            if target_field == "theme_family_id":
                required = {"family_registered": target.get("created_at")}
                if target.get("lifecycle_status") == "retired":
                    required["family_retired"] = target.get("retired_at")
                return required, {}
            if target_field == "theme_family_version_id":
                required = {"family_version_registered": target.get("created_at")}
                optional = {}
                if target.get("lifecycle_status") == "approved":
                    required["family_version_approved"] = target.get(
                        "updated_at"
                    )
                if target.get("lifecycle_status") == "retired":
                    required["family_version_retired"] = target.get("retired_at")
                    # Retirement may follow preview directly or preserve a
                    # prior approval. There is no separate approved_at column,
                    # so approval evidence is optional only in this state.
                    optional["family_version_approved"] = target.get(
                        "created_at"
                    )
                return required, optional
            if target_field == "website_theme_configuration_id":
                required = {
                    (
                        "website_draft_created"
                        if target.get("version") == 1
                        else "website_configuration_revision_created"
                    ): target.get("created_at")
                }
                if target.get("approved_at") is not None:
                    required["website_configuration_approved"] = target.get(
                        "approved_at"
                    )
                if target.get("activated_at") is not None:
                    required["website_configuration_activated"] = target.get(
                        "activated_at"
                    )
                if target.get("lifecycle_status") == "superseded":
                    required["website_configuration_superseded"] = target.get(
                        "updated_at"
                    )
                if target.get("rollback_at") is not None:
                    required["website_configuration_rolled_back"] = target.get(
                        "rollback_at"
                    )
                if target.get("lifecycle_status") == "retired":
                    required["website_configuration_retired"] = target.get(
                        "updated_at"
                    )
                return required, {}

            required = {
                (
                    "component_created"
                    if target.get("revision") == 1
                    else "component_revision_created"
                ): target.get("created_at")
            }
            if target.get("lifecycle_status") == "superseded":
                required["component_superseded"] = target.get("updated_at")
            if target.get("activated_at") is not None:
                required["component_activated"] = target.get("activated_at")
            if target.get("rollback_at") is not None:
                required["component_rolled_back"] = target.get("rollback_at")
            return required, {}

        required_audits: dict[tuple[str, int, str], Any] = {}
        allowed_audits: dict[tuple[str, int, str], Any] = {}
        for target_field, records in {
            "theme_family_id": families,
            "theme_family_version_id": versions,
            "website_theme_configuration_id": configurations,
            "component_configuration_id": components,
        }.items():
            for target_id, target in records.items():
                required, optional = required_audit_actions(
                    target_field,
                    target,
                )
                for action_type, not_before in {**optional, **required}.items():
                    allowed_audits[(target_field, target_id, action_type)] = (
                        not_before
                    )
                for action_type, not_before in required.items():
                    required_audits[(target_field, target_id, action_type)] = (
                        not_before
                    )
        seen_audits: set[tuple[str, int, str]] = set()
        target_groups = {
            "theme_family_id": families,
            "theme_family_version_id": versions,
            "website_theme_configuration_id": configurations,
            "component_configuration_id": components,
        }
        for record in audits.values():
            ThemeConfigurationAuditRead.model_validate(record)
            _require_backup_stored_text(
                record.get("actor"),
                "Theme configuration audit actor",
                160,
            )
            _require_backup_stored_text(
                record.get("rationale"),
                "Theme configuration audit rationale",
                2000,
            )
            populated = [
                field
                for field in target_groups
                if record.get(field) is not None
            ]
            if (
                len(populated) != 1
                or record[populated[0]] not in target_groups[populated[0]]
                or not isinstance(record.get("snapshot"), dict)
                or record.get("snapshot_hash")
                != _canonical_json_hash(
                    _theme_configuration_audit_hash_payload(record)
                )
            ):
                raise BackupValidationError(
                    "Theme configuration audit identity or hash is invalid."
                )
            target_field = populated[0]
            target_id = record[target_field]
            target = target_groups[target_field][target_id]
            action_type = record.get("action_type")
            audit_identity = (target_field, target_id, action_type)
            if (
                audit_identity not in allowed_audits
                or audit_identity in seen_audits
            ):
                raise BackupValidationError(
                    "Theme configuration entity has an unsupported or duplicate "
                    "immutable audit."
                )
            seen_audits.add(audit_identity)
            not_before = allowed_audits[audit_identity]
            if _comparable_datetime(
                _datetime_value(
                    record.get("created_at"),
                    "theme_configuration_audits.created_at",
                )
            ) < _comparable_datetime(
                _datetime_value(
                    not_before,
                    "durable Theme transition timestamp",
                )
            ):
                raise BackupValidationError(
                    "Theme configuration audit chronology precedes its durable transition."
                )
            snapshot = record["snapshot"]
            stable_fields = {
                "theme_family_id": ("family_key",),
                "theme_family_version_id": ("theme_family_id", "version"),
                "website_theme_configuration_id": (
                    "website_id",
                    "theme_family_version_id",
                    "configuration_key",
                    "version",
                ),
                "component_configuration_id": (
                    "website_theme_configuration_id",
                    "website_id",
                    "planned_page_id",
                    "theme_family_version_id",
                    "component_instance_key",
                    "component_key",
                    "component_contract_version",
                    "revision",
                    "scope_type",
                ),
            }[target_field]
            if any(snapshot.get(field) != target.get(field) for field in stable_fields):
                raise BackupValidationError(
                    "Theme configuration audit snapshot crosses its exact target."
                )
            embedded_references = (
                ("website_id", websites),
                ("business_id", businesses),
                ("planned_page_id", planned_pages),
                ("materialized_theme_id", themes),
                ("website_theme_selection_id", selections),
                ("theme_family_id", families),
                ("theme_family_version_id", versions),
                ("supersedes_theme_family_version_id", versions),
                ("website_theme_configuration_id", configurations),
                ("supersedes_configuration_id", configurations),
                ("destination_component_configuration_id", components),
                ("overrides_component_configuration_id", components),
                ("supersedes_component_configuration_id", components),
            )
            if any(
                snapshot.get(field) is not None
                and snapshot[field] not in target_records
                for field, target_records in embedded_references
            ):
                raise BackupValidationError(
                    "Theme configuration audit snapshot contains an unresolved identity."
                )
        if not set(required_audits) <= seen_audits:
            raise BackupValidationError(
                "Theme configuration backup lacks complete exact-target audit coverage."
            )
    except BackupValidationError:
        raise
    except (TypeError, ValueError) as exc:
        raise BackupValidationError(
            "Backup contains invalid durable Theme configuration data."
        ) from exc


def _validate_form_delivery_graph(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    """Reject unsafe or inconsistent Backup 0.58 form-delivery graphs."""

    if backup_version != "0.58":
        if any(data[group] for group in FORM_DELIVERY_BACKUP_GROUPS):
            raise BackupValidationError(
                "Legacy backup contains unsupported form-delivery records."
            )
        return

    from pydantic import EmailStr, TypeAdapter

    from app.schemas.form_delivery import (
        optional_field_definitions_from_configuration,
        validate_mode_configuration,
    )
    from app.services.form_delivery_modes import (
        form_delivery_configuration_audit_hash,
        form_delivery_mode_fingerprint,
        form_recipient_fingerprint,
        normalize_recipient_email,
    )
    from app.services.form_delivery_outbox import (
        form_delivery_attempt_fingerprint,
        form_submission_envelope_fingerprint,
    )
    from app.website_builder_core.contracts import (
        ATLAS_OWNED_FORM_MODES,
        optional_form_field_definition_payload,
    )

    models = {
        "website_form_delivery_mode_revisions": WebsiteFormDeliveryModeRevision,
        "website_form_recipient_revisions": WebsiteFormRecipientRevision,
        "form_submission_envelopes": FormSubmissionEnvelope,
        "form_delivery_outbox_records": FormDeliveryOutbox,
        "form_delivery_attempts": FormDeliveryAttempt,
        "form_delivery_configuration_audits": FormDeliveryConfigurationAudit,
    }
    try:
        for group, model in models.items():
            expected_fields = set(model.model_fields)
            for record in data[group]:
                if set(record) != expected_fields:
                    raise BackupValidationError(
                        f"Backup record in '{group}' does not match the exact 0.58 field contract."
                    )
                _record_id(record, group)
                model.model_validate(
                    _normalize_converged_utc_restore_values(model, record)
                )

        websites = {record["id"]: record for record in data["websites"]}
        components = {
            record["id"]: record
            for record in data["website_theme_component_configurations"]
        }
        modes = {
            record["id"]: record
            for record in data["website_form_delivery_mode_revisions"]
        }
        recipients = {
            record["id"]: record
            for record in data["website_form_recipient_revisions"]
        }
        envelopes = {
            record["id"]: record for record in data["form_submission_envelopes"]
        }
        outboxes = {
            record["id"]: record
            for record in data["form_delivery_outbox_records"]
        }

        if len(modes) != len(data["website_form_delivery_mode_revisions"]):
            raise BackupValidationError(
                "Backup contains duplicate form-delivery mode identities."
            )
        if len(recipients) != len(data["website_form_recipient_revisions"]):
            raise BackupValidationError(
                "Backup contains duplicate form-recipient identities."
            )
        if len(envelopes) != len(data["form_submission_envelopes"]):
            raise BackupValidationError(
                "Backup contains duplicate form-envelope identities."
            )
        if len(outboxes) != len(data["form_delivery_outbox_records"]):
            raise BackupValidationError(
                "Backup contains duplicate form-outbox identities."
            )

        mode_groups: dict[tuple[int, str], list[dict[str, Any]]] = {}
        normalized_mode_configurations: dict[int, dict[str, Any]] = {}
        for record in modes.values():
            website = websites.get(record["website_id"])
            component = components.get(record["form_component_configuration_id"])
            if website is None or component is None:
                raise BackupValidationError(
                    "Backup form-delivery mode has an unresolved Website or component."
                )
            if (
                component.get("website_id") != record["website_id"]
                or component.get("component_instance_key")
                != record["form_instance_key"]
                or component.get("component_key") != "compact_estimate_form"
                or component.get("scope_type") != "website_default"
                or component.get("planned_page_id") is not None
                or component.get("overrides_component_configuration_id") is not None
            ):
                raise BackupValidationError(
                    "Backup form-delivery mode crosses its exact Website/form component scope."
                )
            if (
                not _is_positive_int(record.get("revision"))
                or type(record.get("enabled")) is not bool
                or record.get("lifecycle_status")
                not in {"draft", "approved", "active", "retired"}
                or record.get("mode")
                not in {
                    "disabled",
                    "atlas_email",
                    "provider_owned",
                    "atlasops360_native",
                    "external_adapter",
                }
                or not _is_form_delivery_safe_text(record.get("audit_identity"))
                or not _is_form_delivery_safe_text(record.get("created_by"))
                or not _is_form_delivery_safe_text(record.get("updated_by"))
            ):
                raise BackupValidationError(
                    "Backup contains an invalid form-delivery mode revision."
                )
            created_at = _form_delivery_timestamp(record, "created_at")
            updated_at = _form_delivery_timestamp(record, "updated_at")
            if _comparable_datetime(updated_at) < _comparable_datetime(created_at):
                raise BackupValidationError(
                    "Backup form-delivery mode update predates creation."
                )
            approval_pair = (
                record.get("approval_identity") is not None,
                record.get("approved_at") is not None,
            )
            activation_pair = (
                record.get("activation_identity") is not None,
                record.get("activated_at") is not None,
            )
            if approval_pair[0] != approval_pair[1] or activation_pair[0] != activation_pair[1]:
                raise BackupValidationError(
                    "Backup form-delivery mode has incomplete approval or activation evidence."
                )
            approved_at = None
            if record.get("approved_at") is not None:
                approved_at = _form_delivery_timestamp(record, "approved_at")
                if not _is_form_delivery_safe_text(
                    record.get("approval_identity")
                ):
                    raise BackupValidationError(
                        "Backup form-delivery approval evidence is invalid."
                    )
            if record["lifecycle_status"] in {"approved", "active"} and approved_at is None:
                raise BackupValidationError(
                    "Approved or active form-delivery mode lacks approval evidence."
                )
            if record.get("activated_at") is not None:
                activated_at = _form_delivery_timestamp(record, "activated_at")
                if (
                    not _is_form_delivery_safe_text(record.get("activation_identity"))
                    or _comparable_datetime(activated_at)
                    < _comparable_datetime(approved_at or created_at)
                ):
                    raise BackupValidationError(
                        "Backup form-delivery activation evidence is invalid."
                    )
            elif record["lifecycle_status"] == "active":
                raise BackupValidationError(
                    "Active form-delivery mode lacks activation evidence."
                )
            if record["enabled"] and (
                record["mode"] == "disabled"
                or record["lifecycle_status"] != "active"
            ):
                raise BackupValidationError(
                    "Only an active non-disabled form-delivery mode may be enabled."
                )
            configuration = record.get("configuration_payload")
            if not isinstance(configuration, dict):
                raise BackupValidationError(
                    "Backup form-delivery configuration must be an object."
                )
            normalized_configuration = validate_mode_configuration(
                record["mode"],
                configuration,
            )
            if normalized_configuration != configuration:
                raise BackupValidationError(
                    "Backup form-delivery configuration is not canonical."
                )
            normalized_mode_configurations[record["id"]] = normalized_configuration
            governed_fields = (
                "provider_key",
                "adapter_version",
                "destination_identity",
                "privacy_policy_reference",
                "consent_policy_reference",
                "retention_policy_reference",
                "abuse_policy_reference",
                "success_behavior",
                "failure_behavior",
                "idempotency_policy_reference",
            )
            if record["mode"] == "disabled":
                if configuration or any(
                    record.get(field) is not None for field in governed_fields
                ):
                    raise BackupValidationError(
                        "Disabled form-delivery mode contains delivery configuration."
                    )
            elif any(
                not _is_form_delivery_safe_text(record.get(field))
                for field in (
                    "provider_key",
                    "adapter_version",
                    "destination_identity",
                )
            ):
                raise BackupValidationError(
                    "Non-disabled form-delivery mode lacks provider, adapter, or destination identity."
                )
            if record["mode"] == "provider_owned" and any(
                record.get(field) is not None
                for field in (
                    "consent_policy_reference",
                    "retention_policy_reference",
                    "abuse_policy_reference",
                    "idempotency_policy_reference",
                )
            ):
                raise BackupValidationError(
                    "Provider-owned form mode cannot claim Atlas collection or retention policy."
                )
            if not _is_lower_sha256(record.get("integrity_fingerprint")) or (
                record["integrity_fingerprint"]
                != form_delivery_mode_fingerprint(record)
            ):
                raise BackupValidationError(
                    "Backup form-delivery mode fingerprint is invalid."
                )
            mode_groups.setdefault(
                (record["website_id"], record["form_instance_key"]), []
            ).append(record)

        for records in mode_groups.values():
            ordered = sorted(records, key=lambda item: item["revision"])
            if [item["revision"] for item in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                raise BackupValidationError(
                    "Backup form-delivery mode revisions are not contiguous."
                )
            optional_definitions_by_identity: dict[str, dict[str, object]] = {}
            for record in ordered:
                if record["mode"] not in ATLAS_OWNED_FORM_MODES:
                    continue
                definitions = optional_field_definitions_from_configuration(
                    normalized_mode_configurations[record["id"]]
                )
                if not definitions:
                    continue
                snapshot = optional_form_field_definition_payload(
                    definitions[0]
                )
                identity = str(snapshot["definition_revision_identity"])
                prior = optional_definitions_by_identity.get(identity)
                if prior is not None and prior != snapshot:
                    raise BackupValidationError(
                        "Backup form-delivery lineage reuses an optional field "
                        "definition identity for changed content."
                    )
                optional_definitions_by_identity[identity] = snapshot
            predecessor_ids: set[int] = set()
            for index, record in enumerate(ordered):
                expected_predecessor = ordered[index - 1]["id"] if index else None
                if (
                    record.get("supersedes_delivery_mode_revision_id")
                    != expected_predecessor
                    or (
                        expected_predecessor is not None
                        and expected_predecessor in predecessor_ids
                    )
                ):
                    raise BackupValidationError(
                        "Backup form-delivery mode lineage is branched, cyclic, or cross-scoped."
                    )
                if expected_predecessor is not None:
                    predecessor_ids.add(expected_predecessor)
            heads = [item for item in ordered if item["id"] not in predecessor_ids]
            if len(heads) != 1 or heads[0] is not ordered[-1]:
                raise BackupValidationError(
                    "Backup form-delivery mode chain lacks exactly one current head."
                )

        successor_created_at_by_mode: dict[int, datetime] = {}
        for record in modes.values():
            predecessor_id = record.get("supersedes_delivery_mode_revision_id")
            if predecessor_id is not None:
                successor_created_at_by_mode[predecessor_id] = (
                    _form_delivery_timestamp(record, "created_at")
                )
        first_envelope_received_at_by_mode: dict[int, datetime] = {}
        for envelope in envelopes.values():
            mode_id = envelope["delivery_mode_revision_id"]
            received_at = _form_delivery_timestamp(envelope, "received_at")
            prior = first_envelope_received_at_by_mode.get(mode_id)
            if prior is None or _comparable_datetime(received_at) < (
                _comparable_datetime(prior)
            ):
                first_envelope_received_at_by_mode[mode_id] = received_at

        email_adapter = TypeAdapter(EmailStr)
        recipient_groups: dict[
            tuple[int, str, str], list[dict[str, Any]]
        ] = {}
        for record in recipients.values():
            mode = modes.get(record["delivery_mode_revision_id"])
            if (
                mode is None
                or mode["mode"] != "atlas_email"
                or mode["website_id"] != record["website_id"]
                or mode["form_component_configuration_id"]
                != record["form_component_configuration_id"]
                or mode["form_instance_key"] != record["form_instance_key"]
            ):
                raise BackupValidationError(
                    "Backup form recipient crosses its exact Atlas-email mode scope."
                )
            if (
                not _is_positive_int(record.get("revision"))
                or type(record.get("enabled")) is not bool
                or record.get("recipient_role") not in {"primary", "secondary"}
                or record.get("verification_status")
                not in {"unverified", "verified", "revoked"}
                or not _is_form_delivery_safe_text(record.get("recipient_key"))
                or not _is_form_delivery_safe_text(record.get("created_by"))
                or not _is_form_delivery_safe_text(record.get("updated_by"))
            ):
                raise BackupValidationError(
                    "Backup contains an invalid form-recipient revision."
                )
            email = str(email_adapter.validate_python(record.get("email")))
            if (
                record.get("normalized_email") != normalize_recipient_email(email)
                or normalize_recipient_email(record["email"])
                != record["normalized_email"]
            ):
                raise BackupValidationError(
                    "Backup form recipient email is not deterministically normalized."
                )
            created_at = _form_delivery_timestamp(record, "created_at")
            updated_at = _form_delivery_timestamp(record, "updated_at")
            if _comparable_datetime(updated_at) < _comparable_datetime(created_at):
                raise BackupValidationError(
                    "Backup form-recipient update predates creation."
                )
            mode_created_at = _form_delivery_timestamp(mode, "created_at")
            seal_times = [
                value
                for value in (
                    successor_created_at_by_mode.get(mode["id"]),
                    first_envelope_received_at_by_mode.get(mode["id"]),
                )
                if value is not None
            ]
            if _comparable_datetime(created_at) < _comparable_datetime(
                mode_created_at
            ) or any(
                _comparable_datetime(created_at) > _comparable_datetime(seal_time)
                for seal_time in seal_times
            ):
                raise BackupValidationError(
                    "Backup form-recipient creation falls outside its immutable mode snapshot."
                )
            verification_fields = (
                record.get("verified_at"),
                record.get("verified_by"),
                record.get("verification_method"),
            )
            if record["verification_status"] == "unverified":
                if any(value is not None for value in verification_fields):
                    raise BackupValidationError(
                        "Unverified form recipient contains verification evidence."
                    )
            else:
                if (
                    any(value is None for value in verification_fields)
                    or not _is_form_delivery_safe_text(record.get("verified_by"))
                    or not _is_form_delivery_safe_text(
                        record.get("verification_method")
                    )
                ):
                    raise BackupValidationError(
                        "Verified or revoked form recipient lacks valid provenance."
                    )
                _form_delivery_timestamp(record, "verified_at")
            if not _is_lower_sha256(record.get("integrity_fingerprint")) or (
                record["integrity_fingerprint"] != form_recipient_fingerprint(record)
            ):
                raise BackupValidationError(
                    "Backup form-recipient fingerprint is invalid."
                )
            recipient_groups.setdefault(
                (
                    record["website_id"],
                    record["form_instance_key"],
                    record["recipient_key"],
                ),
                [],
            ).append(record)

        recipient_predecessor_ids: set[int] = set()
        same_mode_recipient_predecessor_ids: dict[int, set[int]] = {}
        for records in recipient_groups.values():
            ordered = sorted(records, key=lambda item: item["revision"])
            if [item["revision"] for item in ordered] != list(
                range(1, len(ordered) + 1)
            ):
                raise BackupValidationError(
                    "Backup form-recipient revisions are not contiguous."
                )
            predecessor_ids: set[int] = set()
            for index, record in enumerate(ordered):
                expected_predecessor = ordered[index - 1]["id"] if index else None
                predecessor = ordered[index - 1] if index else None
                current_mode = modes.get(record["delivery_mode_revision_id"])
                predecessor_mode = (
                    modes.get(predecessor["delivery_mode_revision_id"])
                    if predecessor is not None
                    else None
                )
                if (
                    record.get("supersedes_recipient_revision_id")
                    != expected_predecessor
                    or (
                        expected_predecessor is not None
                        and expected_predecessor in predecessor_ids
                    )
                    or (
                        predecessor_mode is not None
                        and (
                            current_mode is None
                            or not (
                                current_mode["id"] == predecessor_mode["id"]
                                or current_mode.get(
                                    "supersedes_delivery_mode_revision_id"
                                )
                                == predecessor_mode["id"]
                            )
                        )
                    )
                ):
                    raise BackupValidationError(
                        "Backup form-recipient lineage is branched, cyclic, or cross-scoped."
                    )
                if expected_predecessor is not None:
                    predecessor_ids.add(expected_predecessor)
                    recipient_predecessor_ids.add(expected_predecessor)
                    if current_mode["id"] == predecessor_mode["id"]:
                        same_mode_recipient_predecessor_ids.setdefault(
                            current_mode["id"], set()
                        ).add(expected_predecessor)
            heads = [item for item in ordered if item["id"] not in predecessor_ids]
            if len(heads) != 1 or heads[0] is not ordered[-1]:
                raise BackupValidationError(
                    "Backup form-recipient chain lacks exactly one current head."
                )

        recipient_heads_by_mode: dict[int, list[dict[str, Any]]] = {}
        for record in recipients.values():
            if record["id"] not in same_mode_recipient_predecessor_ids.get(
                record["delivery_mode_revision_id"], set()
            ):
                recipient_heads_by_mode.setdefault(
                    record["delivery_mode_revision_id"], []
                ).append(record)
        for heads in recipient_heads_by_mode.values():
            normalized_addresses = [record["normalized_email"] for record in heads]
            if len(normalized_addresses) != len(set(normalized_addresses)):
                raise BackupValidationError(
                    "Backup form mode contains duplicate current normalized recipient heads."
                )
            if sum(
                1
                for record in heads
                if record["enabled"] and record["recipient_role"] == "primary"
            ) > 1:
                raise BackupValidationError(
                    "Backup form mode contains multiple enabled primary recipient heads."
                )

        _validate_form_delivery_runtime_records(
            envelopes=envelopes,
            outboxes=outboxes,
            attempts=data["form_delivery_attempts"],
            modes=modes,
            envelope_fingerprint=form_submission_envelope_fingerprint,
            attempt_fingerprint=form_delivery_attempt_fingerprint,
        )
        _validate_form_delivery_audits(
            audits=data["form_delivery_configuration_audits"],
            modes=modes,
            recipients=recipients,
            audit_hash=form_delivery_configuration_audit_hash,
        )
    except BackupValidationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise BackupValidationError(
            "Backup contains invalid universal form-delivery data."
        ) from exc


def _validate_form_delivery_runtime_records(
    *,
    envelopes: dict[int, dict[str, Any]],
    outboxes: dict[int, dict[str, Any]],
    attempts: list[dict[str, Any]],
    modes: dict[int, dict[str, Any]],
    envelope_fingerprint: Any,
    attempt_fingerprint: Any,
) -> None:
    for record in envelopes.values():
        mode = modes.get(record["delivery_mode_revision_id"])
        if (
            mode is None
            or mode["mode"] not in _FORM_DELIVERY_COLLECTOR_MODES
            or mode["lifecycle_status"] != "active"
            or mode["enabled"] is not True
            or mode["website_id"] != record["website_id"]
            or mode["form_component_configuration_id"]
            != record["form_component_configuration_id"]
            or mode["provider_key"] != record["destination_adapter_key"]
            or mode["privacy_policy_reference"]
            != record["privacy_policy_reference"]
            or mode["retention_policy_reference"]
            != record["retention_policy_reference"]
            or mode["abuse_policy_reference"] != record["abuse_policy_reference"]
            or mode["audit_identity"] != record["audit_identity"]
        ):
            raise BackupValidationError(
                "Backup form envelope crosses mode scope or durable policy."
            )
        if (
            not _is_positive_int(record.get("submission_contract_version"))
            or (
                record.get("consent_accepted") is not None
                and type(record.get("consent_accepted")) is not bool
            )
            or not _is_form_delivery_safe_text(record.get("privacy_policy_reference"))
            or not _is_form_delivery_safe_text(record.get("retention_policy_reference"))
            or not _is_form_delivery_safe_text(record.get("abuse_policy_reference"))
            or not _is_form_delivery_stable_key(record.get("anti_spam_decision"))
            or not _is_form_delivery_stable_key(record.get("audit_identity"))
            or not _is_lower_sha256(record.get("request_identity"))
            or not _is_form_delivery_stable_key(
                record.get("destination_adapter_key")
            )
            or not _is_lower_sha256(record.get("idempotency_digest"))
            or (
                record.get("consent_version") is not None
                and not _is_form_delivery_stable_key(record.get("consent_version"))
            )
            or (
                record.get("source_page_identity") is not None
                and not _is_form_delivery_source_reference(
                    record.get("source_page_identity")
                )
            )
        ):
            raise BackupValidationError(
                "Backup contains invalid safe form-envelope metadata."
            )
        received_at = _form_delivery_timestamp(record, "received_at")
        expires_at = None
        if record.get("expires_at") is not None:
            expires_at = _form_delivery_timestamp(record, "expires_at")
            if _comparable_datetime(expires_at) < _comparable_datetime(received_at):
                raise BackupValidationError(
                    "Backup form envelope expires before receipt."
                )
        payload_reference = record.get("secure_payload_reference")
        key_reference = record.get("encryption_key_reference")
        if (payload_reference is None) != (key_reference is None):
            raise BackupValidationError(
                "Backup form envelope has incomplete secure-payload references."
            )
        if payload_reference is None:
            raise BackupValidationError(
                "Backup form envelope lacks its governed secure-payload reference."
            )
        if (
            not isinstance(payload_reference, str)
            or _FORM_DELIVERY_TEST_PAYLOAD_REFERENCE_PATTERN.fullmatch(
                payload_reference
            )
            is None
            or key_reference != _FORM_DELIVERY_TEST_KEY_REFERENCE
        ):
            raise BackupValidationError(
                "Backup 0.58 form envelope may contain only opaque disposable-test payload references."
            )
        if not _is_lower_sha256(record.get("integrity_fingerprint")) or (
            record["integrity_fingerprint"] != envelope_fingerprint(record)
        ):
            raise BackupValidationError(
                "Backup form-envelope fingerprint is invalid."
            )

    attempt_ids: set[int] = set()
    attempt_keys: set[tuple[int, int]] = set()
    attempts_by_outbox: dict[int, list[dict[str, Any]]] = {}
    for record in attempts:
        record_id = _record_id(record, "form_delivery_attempts")
        key = (record["outbox_id"], record["attempt_number"])
        if record_id in attempt_ids or key in attempt_keys:
            raise BackupValidationError(
                "Backup contains duplicate form-delivery attempts."
            )
        attempt_ids.add(record_id)
        attempt_keys.add(key)
        if (
            record["outbox_id"] not in outboxes
            or not _is_positive_int(record.get("attempt_number"))
            or record.get("outcome")
            not in {"delivered", "transient_failure", "permanent_failure"}
            or (
                record.get("safe_error_code") is not None
                and not _is_form_delivery_safe_code(record.get("safe_error_code"))
            )
            or (
                record.get("safe_provider_reference") is not None
                and not _is_lower_sha256(record.get("safe_provider_reference"))
            )
        ):
            raise BackupValidationError(
                "Backup contains invalid value-free form-delivery attempt evidence."
            )
        started_at = _form_delivery_timestamp(record, "started_at")
        completed_at = _form_delivery_timestamp(record, "completed_at")
        if _comparable_datetime(completed_at) < _comparable_datetime(started_at):
            raise BackupValidationError(
                "Backup form-delivery attempt completes before it starts."
            )
        if record["outcome"] == "transient_failure":
            if record.get("next_retry_at") is None:
                raise BackupValidationError(
                    "Transient form-delivery failure lacks retry evidence."
                )
            next_retry_at = _form_delivery_timestamp(record, "next_retry_at")
            if _comparable_datetime(next_retry_at) < _comparable_datetime(
                completed_at
            ):
                raise BackupValidationError(
                    "Backup form-delivery retry predates attempt completion."
                )
        elif record.get("next_retry_at") is not None:
            raise BackupValidationError(
                "Non-transient form-delivery attempt contains retry evidence."
            )
        if record["outcome"] == "delivered":
            if (
                record.get("safe_error_code") is not None
                or not _is_lower_sha256(record.get("safe_provider_reference"))
            ):
                raise BackupValidationError(
                    "Delivered form attempt lacks exact value-free provider evidence."
                )
        elif not _is_form_delivery_safe_code(record.get("safe_error_code")):
            raise BackupValidationError(
                "Failed form-delivery attempt lacks a safe error code."
            )
        if not _is_lower_sha256(record.get("integrity_fingerprint")) or (
            record["integrity_fingerprint"] != attempt_fingerprint(record)
        ):
            raise BackupValidationError(
                "Backup form-delivery attempt fingerprint is invalid."
            )
        attempts_by_outbox.setdefault(record["outbox_id"], []).append(record)

    envelope_outboxes: set[int] = set()
    for record in outboxes.values():
        envelope = envelopes.get(record["envelope_id"])
        mode = modes.get(record["delivery_mode_revision_id"])
        if (
            envelope is None
            or mode is None
            or record["envelope_id"] in envelope_outboxes
            or envelope["delivery_mode_revision_id"]
            != record["delivery_mode_revision_id"]
            or record["adapter_key"] != mode["provider_key"]
            or record["adapter_version"] != mode["adapter_version"]
            or record["destination_identity"] != mode["destination_identity"]
        ):
            raise BackupValidationError(
                "Backup form outbox crosses its exact envelope or mode scope."
            )
        envelope_outboxes.add(record["envelope_id"])
        if (
            record.get("status")
            not in {
                "queued",
                "processing",
                "retrying",
                "delivered",
                "terminal_failed",
                "expired",
            }
            or type(record.get("attempt_count")) is not int
            or record["attempt_count"] < 0
            or not _is_positive_int(record.get("state_version"))
            or not _is_form_delivery_safe_text(record.get("adapter_key"))
            or not _is_form_delivery_safe_text(record.get("adapter_version"))
            or not _is_form_delivery_safe_text(record.get("destination_identity"))
            or (
                record.get("last_safe_error_code") is not None
                and not _is_form_delivery_safe_code(record.get("last_safe_error_code"))
            )
        ):
            raise BackupValidationError(
                "Backup contains invalid form-delivery outbox state."
            )
        created_at = _form_delivery_timestamp(record, "created_at")
        updated_at = _form_delivery_timestamp(record, "updated_at")
        if (
            _comparable_datetime(updated_at) < _comparable_datetime(created_at)
            or _comparable_datetime(created_at)
            < _comparable_datetime(
                _form_delivery_timestamp(envelope, "received_at")
            )
        ):
            raise BackupValidationError(
                "Backup form-delivery outbox chronology is invalid."
            )
        ordered_attempts = sorted(
            attempts_by_outbox.get(record["id"], []),
            key=lambda item: item["attempt_number"],
        )
        if (
            record["attempt_count"] != len(ordered_attempts)
            or [item["attempt_number"] for item in ordered_attempts]
            != list(range(1, len(ordered_attempts) + 1))
            or record["state_version"] < record["attempt_count"] + 1
        ):
            raise BackupValidationError(
                "Backup form outbox attempt count or state version is inconsistent."
            )
        latest = ordered_attempts[-1] if ordered_attempts else None
        if latest is not None:
            if (
                _comparable_datetime(
                    _form_delivery_timestamp(latest, "completed_at")
                )
                > _comparable_datetime(updated_at)
                or record.get("last_safe_error_code")
                != latest.get("safe_error_code")
            ):
                raise BackupValidationError(
                    "Backup form outbox does not match its latest attempt evidence."
                )
        elif record.get("last_safe_error_code") is not None:
            raise BackupValidationError(
                "Attempt-free form outbox contains a last error."
            )
        terminal_values = {
            field: record.get(field)
            for field in ("delivered_at", "failed_at", "expired_at")
        }
        for field, value in terminal_values.items():
            if value is not None:
                _form_delivery_timestamp(record, field)
        status = record["status"]
        if status == "queued":
            if latest is not None or record.get("next_attempt_at") is not None or any(
                value is not None for value in terminal_values.values()
            ):
                raise BackupValidationError(
                    "Queued form outbox contains attempt or terminal evidence."
                )
        elif status == "retrying":
            if (
                latest is None
                or latest["outcome"] != "transient_failure"
                or record.get("next_attempt_at") is None
                or any(value is not None for value in terminal_values.values())
                or _comparable_datetime(
                    _form_delivery_timestamp(record, "next_attempt_at")
                )
                != _comparable_datetime(
                    _form_delivery_timestamp(latest, "next_retry_at")
                )
            ):
                raise BackupValidationError(
                    "Retrying form outbox lacks exact transient-failure evidence."
                )
        elif status == "delivered":
            if (
                latest is None
                or latest["outcome"] != "delivered"
                or terminal_values["delivered_at"] is None
                or terminal_values["failed_at"] is not None
                or terminal_values["expired_at"] is not None
                or record.get("next_attempt_at") is not None
            ):
                raise BackupValidationError(
                    "Delivered form outbox lacks exact terminal evidence."
                )
        elif status == "terminal_failed":
            if (
                latest is None
                or latest["outcome"] != "permanent_failure"
                or terminal_values["failed_at"] is None
                or terminal_values["delivered_at"] is not None
                or terminal_values["expired_at"] is not None
                or record.get("next_attempt_at") is not None
            ):
                raise BackupValidationError(
                    "Terminally failed form outbox lacks exact failure evidence."
                )
        elif status == "expired":
            if (
                terminal_values["expired_at"] is None
                or terminal_values["delivered_at"] is not None
                or terminal_values["failed_at"] is not None
                or record.get("next_attempt_at") is not None
                or envelope.get("expires_at") is None
                or _comparable_datetime(
                    _form_delivery_timestamp(record, "expired_at")
                )
                < _comparable_datetime(
                    _form_delivery_timestamp(envelope, "expires_at")
                )
            ):
                raise BackupValidationError(
                    "Expired form outbox lacks exact expiration evidence."
                )
        elif any(value is not None for value in terminal_values.values()):
            raise BackupValidationError(
                "Processing form outbox contains terminal evidence."
            )

    if envelope_outboxes != set(envelopes):
        raise BackupValidationError(
            "Every backup form envelope must have exactly one delivery outbox."
        )

    if set(attempts_by_outbox) - set(outboxes):
        raise BackupValidationError(
            "Backup form-delivery attempt references an unresolved outbox."
        )


def _validate_form_delivery_audits(
    *,
    audits: list[dict[str, Any]],
    modes: dict[int, dict[str, Any]],
    recipients: dict[int, dict[str, Any]],
    audit_hash: Any,
) -> None:
    audit_ids: set[int] = set()
    hashes: set[str] = set()
    covered_modes: set[int] = set()
    covered_recipients: set[int] = set()
    mode_snapshot_fields = {
        "target",
        "target_id",
        "website_id",
        "form_component_configuration_id",
        "revision",
        "mode",
        "lifecycle_status",
        "integrity_fingerprint",
    }
    recipient_snapshot_fields = {
        "target",
        "target_id",
        "website_id",
        "form_component_configuration_id",
        "revision",
        "recipient_key",
        "verification_status",
        "integrity_fingerprint",
    }
    for record in audits:
        record_id = _record_id(record, "form_delivery_configuration_audits")
        snapshot_hash = record.get("snapshot_hash")
        if (
            record_id in audit_ids
            or snapshot_hash in hashes
            or not _is_lower_sha256(snapshot_hash)
            or not _is_form_delivery_safe_text(record.get("actor"))
            or not _is_form_delivery_safe_text(record.get("rationale"))
        ):
            raise BackupValidationError(
                "Backup contains duplicate or unsafe form-delivery audit evidence."
            )
        audit_ids.add(record_id)
        hashes.add(snapshot_hash)
        mode_id = record.get("delivery_mode_revision_id")
        recipient_id = record.get("recipient_revision_id")
        exact_target = (mode_id is not None) + (recipient_id is not None)
        if exact_target != 1 or not isinstance(record.get("snapshot"), dict):
            raise BackupValidationError(
                "Backup form-delivery audit must have exactly one safe target."
            )
        snapshot = record["snapshot"]
        if mode_id is not None:
            target = modes.get(mode_id)
            if target is None or mode_id in covered_modes:
                raise BackupValidationError(
                    "Backup form-delivery mode audit target is unresolved or duplicated."
                )
            covered_modes.add(mode_id)
            expected_action = {
                "approved": "mode_revision_approved",
                "active": "mode_revision_activated",
                "retired": "mode_revision_retired",
            }.get(target["lifecycle_status"], "mode_revision_created")
            expected_snapshot = {
                "target": "mode_revision",
                "target_id": target["id"],
                "website_id": target["website_id"],
                "form_component_configuration_id": target[
                    "form_component_configuration_id"
                ],
                "revision": target["revision"],
                "mode": target["mode"],
                "lifecycle_status": target["lifecycle_status"],
                "integrity_fingerprint": target["integrity_fingerprint"],
            }
            expected_fields = mode_snapshot_fields
        else:
            target = recipients.get(recipient_id)
            if target is None or recipient_id in covered_recipients:
                raise BackupValidationError(
                    "Backup form-recipient audit target is unresolved or duplicated."
                )
            covered_recipients.add(recipient_id)
            expected_action = {
                "verified": "recipient_verified",
                "revoked": "recipient_revoked",
            }.get(target["verification_status"], "recipient_revision_created")
            expected_snapshot = {
                "target": "recipient_revision",
                "target_id": target["id"],
                "website_id": target["website_id"],
                "form_component_configuration_id": target[
                    "form_component_configuration_id"
                ],
                "revision": target["revision"],
                "recipient_key": target["recipient_key"],
                "verification_status": target["verification_status"],
                "integrity_fingerprint": target["integrity_fingerprint"],
            }
            expected_fields = recipient_snapshot_fields
        if (
            set(snapshot) != expected_fields
            or snapshot != expected_snapshot
            or record.get("action_type") != expected_action
            or record["snapshot_hash"] != audit_hash(record)
        ):
            raise BackupValidationError(
                "Backup form-delivery audit snapshot, action, or hash is invalid."
            )
        if _comparable_datetime(
            _form_delivery_timestamp(record, "created_at")
        ) < _comparable_datetime(_form_delivery_timestamp(target, "created_at")):
            raise BackupValidationError(
                "Backup form-delivery audit predates its immutable target."
            )
    if covered_modes != set(modes) or covered_recipients != set(recipients):
        raise BackupValidationError(
            "Backup form-delivery graph lacks complete exact-target audit coverage."
        )


def _form_delivery_timestamp(record: dict[str, Any], field: str) -> datetime:
    return _datetime_value(record.get(field), f"form_delivery.{field}")


def _is_form_delivery_safe_text(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and value == value.strip()
        and value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
    )


def _is_form_delivery_safe_code(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[a-z0-9_-]{1,120}", value) is not None
    )


def _is_form_delivery_stable_key(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and _FORM_DELIVERY_STABLE_METADATA_KEY_PATTERN.fullmatch(value) is not None
    )


def _is_form_delivery_source_reference(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and _FORM_DELIVERY_OPAQUE_SOURCE_REFERENCE_PATTERN.fullmatch(value)
        is not None
    )


def _is_lower_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _validate_unique_records(data: dict[str, list[dict[str, Any]]]) -> None:
    key_fields: dict[str, tuple[str, ...]] = {
        "businesses": ("company_name",),
        "services": ("service_slug",),
        "counties": ("state", "county_name"),
        "cities": ("city_slug",),
        "generated_pages": ("website_id", "page_slug"),
        "site_plans": ("website_id", "plan_key"),
        "planned_pages": ("website_id", "intended_slug"),
        "planning_records": ("planned_page_id",),
        "website_media_planning_records": ("site_plan_id", "version"),
        "planned_page_media_requirements": (
            "planned_page_id",
            "placement_key",
            "version",
        ),
        "site_connection_planning_records": ("site_plan_id",),
        "website_coverage_planning_records": ("site_plan_id",),
        "website_service_coverage_decisions": ("website_id", "service_id"),
        "website_county_coverage_decisions": ("website_id", "county_id"),
        "website_city_coverage_decisions": ("website_id", "city_id"),
        "website_service_city_coverage_decisions": (
            "website_id",
            "service_id",
            "city_id",
        ),
        "website_service_county_coverage_decisions": (
            "website_id",
            "service_id",
            "county_id",
        ),
        "supporting_page_authorizations": ("planned_page_id",),
        "pre_draft_distinctness_briefs": ("planned_page_id",),
        "drafting_eligibility_assessments": ("planned_page_id",),
        "drafting_eligibility_dispositions": ("planned_page_id",),
        "website_draft_generation_runs": ("site_plan_id", "manifest_hash"),
        "website_draft_generation_items": ("run_id", "inventory_key"),
        "navigation_sets": ("site_plan_id", "set_type"),
        "navigation_items": ("navigation_set_id", "target_planned_page_id"),
        "internal_link_intents": (
            "site_plan_id",
            "source_planned_page_id",
            "target_planned_page_id",
        ),
        "semantic_component_definitions": ("component_key", "contract_version"),
        "page_compositions": ("planned_page_id",),
        "theme_families": ("family_key",),
        "theme_family_versions": ("theme_family_id", "version"),
        "website_theme_configurations": (
            "website_id",
            "theme_family_version_id",
            "configuration_key",
            "version",
        ),
        "website_theme_component_configurations": (
            "website_theme_configuration_id",
            "component_instance_key",
            "revision",
        ),
        "theme_configuration_audits": ("snapshot_hash",),
        "website_form_delivery_mode_revisions": (
            "website_id",
            "form_instance_key",
            "revision",
        ),
        "website_form_recipient_revisions": (
            "website_id",
            "form_instance_key",
            "recipient_key",
            "revision",
        ),
        "form_submission_envelopes": (
            "website_id",
            "form_component_configuration_id",
            "idempotency_digest",
        ),
        "form_delivery_outbox_records": ("envelope_id",),
        "form_delivery_attempts": ("outbox_id", "attempt_number"),
        "form_delivery_configuration_audits": ("snapshot_hash",),
        "brand_assets": ("brand_id", "asset_key", "version"),
        "website_identity_asset_assignments": (
            "website_identity_id",
            "slot",
            "version",
        ),
        "themes": ("website_id", "theme_key", "version"),
        "website_theme_selections": ("website_id", "version"),
        "approval_audits": ("generated_page_id", "approved_at", "draft_hash_at_approval"),
        "page_revisions": ("generated_page_id", "created_at", "draft_hash_after"),
        "generated_page_qa_results": ("generated_page_id", "result_hash"),
        "wordpress_draft_audits": ("generated_page_id", "attempted_at", "payload_hash"),
        "wordpress_heading_correction_audits": ("token_fingerprint",),
        "wordpress_deployment_audits": ("generated_page_id", "attempted_at", "action_type"),
        "wordpress_deployment_nonces": ("jti",),
        "wordpress_deployment_transitions": ("request_identifier",),
        "wordpress_activation_audits": ("handle_fingerprint",),
        "wordpress_plugin_upgrade_audits": ("handle_fingerprint",),
        "wordpress_bootstrap_cleanup_audits": ("deactivation_handle_fingerprint",),
        "wordpress_bootstrap_establishment_audits": ("manual_handle_fingerprint",),
        "wordpress_metadata_lifecycle_audits": ("handle_fingerprint",),
        "wordpress_cache_aware_rendering_audits": ("rendering_handle_fingerprint",),
        "wordpress_publish_audits": ("generated_page_id", "attempted_at", "publish_payload_hash"),
        "wordpress_media_sync_audits": ("generated_page_id", "attempted_at", "source_checksum"),
        "wordpress_metadata_states": ("generated_page_id",),
        "wordpress_metadata_sync_audits": ("generated_page_id", "attempted_at", "payload_hash"),
        "wordpress_quality_reviews": ("generated_page_id",),
        "image_metadata": ("business_id", "file_name"),
        "page_image_assignments": ("generated_page_id", "image_metadata_id", "image_role"),
        "scoped_media_authorizations": (
            "media_requirement_id",
            "authorization_version",
        ),
        "settings": ("setting_key",),
        "knowledge_blocks": ("slug",),
    }
    for group, fields in key_fields.items():
        seen: set[tuple[Any, ...]] = set()
        ids: set[int] = set()
        for record in data[group]:
            record_id = _record_id(record, group)
            if group == "generated_pages":
                owner = record.get("website_id")
                if owner is None:
                    owner = f"legacy-business:{record.get('business_id')}"
                key = (owner, record.get("page_slug"))
            elif group == "image_metadata" and all(
                record.get(field) is not None
                for field in ("website_id", "media_key", "media_version")
            ):
                key = (
                    record.get("website_id"),
                    record.get("media_key"),
                    record.get("media_version"),
                )
            elif group == "page_image_assignments" and all(
                record.get(field) is not None
                for field in ("media_requirement_id", "assignment_version")
            ):
                key = (
                    record.get("media_requirement_id"),
                    record.get("assignment_version"),
                )
            else:
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
        "brands": (("business_id", "businesses", False),),
        "websites": (
            ("business_id", "businesses", False),
            ("brand_id", "brands", True),
        ),
        "website_identities": (("website_id", "websites", False),),
        "brand_assets": (
            ("business_id", "businesses", False),
            ("brand_id", "brands", False),
            ("replaces_brand_asset_id", "brand_assets", True),
        ),
        "website_identity_asset_assignments": (
            ("website_identity_id", "website_identities", False),
            ("website_id", "websites", False),
            ("brand_id", "brands", False),
            ("brand_asset_id", "brand_assets", False),
        ),
        "themes": (
            ("website_id", "websites", False),
            ("business_id", "businesses", False),
            ("brand_id", "brands", False),
            ("replaces_theme_id", "themes", True),
        ),
        "website_theme_selections": (
            ("website_id", "websites", False),
            ("theme_id", "themes", False),
        ),
        "theme_family_versions": (
            ("theme_family_id", "theme_families", False),
            (
                "supersedes_theme_family_version_id",
                "theme_family_versions",
                True,
            ),
        ),
        "website_theme_configurations": (
            ("website_id", "websites", False),
            ("business_id", "businesses", False),
            ("theme_family_version_id", "theme_family_versions", False),
            ("materialized_theme_id", "themes", True),
            ("website_theme_selection_id", "website_theme_selections", True),
            (
                "supersedes_configuration_id",
                "website_theme_configurations",
                True,
            ),
        ),
        "website_theme_component_configurations": (
            (
                "website_theme_configuration_id",
                "website_theme_configurations",
                False,
            ),
            ("website_id", "websites", False),
            ("planned_page_id", "planned_pages", True),
            ("theme_family_version_id", "theme_family_versions", False),
            (
                "destination_component_configuration_id",
                "website_theme_component_configurations",
                True,
            ),
            (
                "overrides_component_configuration_id",
                "website_theme_component_configurations",
                True,
            ),
            (
                "supersedes_component_configuration_id",
                "website_theme_component_configurations",
                True,
            ),
        ),
        "theme_configuration_audits": (
            ("theme_family_id", "theme_families", True),
            ("theme_family_version_id", "theme_family_versions", True),
            (
                "website_theme_configuration_id",
                "website_theme_configurations",
                True,
            ),
            (
                "component_configuration_id",
                "website_theme_component_configurations",
                True,
            ),
        ),
        "website_form_delivery_mode_revisions": (
            ("website_id", "websites", False),
            (
                "form_component_configuration_id",
                "website_theme_component_configurations",
                False,
            ),
            (
                "supersedes_delivery_mode_revision_id",
                "website_form_delivery_mode_revisions",
                True,
            ),
        ),
        "website_form_recipient_revisions": (
            (
                "delivery_mode_revision_id",
                "website_form_delivery_mode_revisions",
                False,
            ),
            ("website_id", "websites", False),
            (
                "form_component_configuration_id",
                "website_theme_component_configurations",
                False,
            ),
            (
                "supersedes_recipient_revision_id",
                "website_form_recipient_revisions",
                True,
            ),
        ),
        "form_submission_envelopes": (
            ("website_id", "websites", False),
            (
                "form_component_configuration_id",
                "website_theme_component_configurations",
                False,
            ),
            (
                "delivery_mode_revision_id",
                "website_form_delivery_mode_revisions",
                False,
            ),
        ),
        "form_delivery_outbox_records": (
            ("envelope_id", "form_submission_envelopes", False),
            (
                "delivery_mode_revision_id",
                "website_form_delivery_mode_revisions",
                False,
            ),
        ),
        "form_delivery_attempts": (
            ("outbox_id", "form_delivery_outbox_records", False),
        ),
        "form_delivery_configuration_audits": (
            (
                "delivery_mode_revision_id",
                "website_form_delivery_mode_revisions",
                True,
            ),
            (
                "recipient_revision_id",
                "website_form_recipient_revisions",
                True,
            ),
        ),
        "services": (("business_id", "businesses", False),),
        "cities": (("county_id", "counties", False),),
        "generated_pages": (
            ("business_id", "businesses", False),
            ("service_id", "services", True),
            ("city_id", "cities", True),
            ("county_id", "counties", True),
            ("website_id", "websites", True),
        ),
        "site_plans": (("website_id", "websites", False),),
        "planned_pages": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("service_id", "services", True),
            ("city_id", "cities", True),
            ("county_id", "counties", True),
            ("parent_planned_page_id", "planned_pages", True),
            ("generated_page_id", "generated_pages", True),
        ),
        "planning_records": (
            ("planned_page_id", "planned_pages", False),
        ),
        "website_media_planning_records": (
            ("website_id", "websites", False),
            ("business_id", "businesses", False),
            ("site_plan_id", "site_plans", False),
            (
                "replaces_record_id",
                "website_media_planning_records",
                True,
            ),
        ),
        "planned_page_media_requirements": (
            ("website_id", "websites", False),
            ("business_id", "businesses", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
            (
                "planning_record_id",
                "website_media_planning_records",
                False,
            ),
            (
                "replaces_requirement_id",
                "planned_page_media_requirements",
                True,
            ),
        ),
        "site_connection_planning_records": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
        ),
        "website_coverage_planning_records": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
        ),
        "website_service_coverage_decisions": (
            ("website_id", "websites", False),
            ("service_id", "services", False),
        ),
        "website_county_coverage_decisions": (
            ("website_id", "websites", False),
            ("county_id", "counties", False),
        ),
        "website_city_coverage_decisions": (
            ("website_id", "websites", False),
            ("city_id", "cities", False),
        ),
        "website_service_city_coverage_decisions": (
            ("website_id", "websites", False),
            ("service_id", "services", False),
            ("city_id", "cities", False),
        ),
        "website_service_county_coverage_decisions": (
            ("website_id", "websites", False),
            ("service_id", "services", False),
            ("county_id", "counties", False),
        ),
        "supporting_page_authorizations": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
        ),
        "pre_draft_distinctness_briefs": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
        ),
        "drafting_eligibility_assessments": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
        ),
        "drafting_eligibility_dispositions": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
            ("assessment_id", "drafting_eligibility_assessments", False),
        ),
        "website_draft_generation_runs": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
        ),
        "website_draft_generation_items": (
            ("run_id", "website_draft_generation_runs", False),
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", True),
            ("generated_page_id", "generated_pages", True),
            ("assessment_id", "drafting_eligibility_assessments", True),
        ),
        "navigation_sets": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
        ),
        "navigation_items": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("navigation_set_id", "navigation_sets", False),
            ("target_planned_page_id", "planned_pages", False),
            ("parent_navigation_item_id", "navigation_items", True),
        ),
        "internal_link_intents": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("source_planned_page_id", "planned_pages", False),
            ("target_planned_page_id", "planned_pages", False),
        ),
        "page_compositions": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
            ("generated_page_id", "generated_pages", False),
        ),
        "image_metadata": (
            ("business_id", "businesses", False),
            ("website_id", "websites", True),
            ("service_id", "services", True),
            ("city_id", "cities", True),
            ("county_id", "counties", True),
            ("replaces_image_metadata_id", "image_metadata", True),
        ),
        "knowledge_blocks": (
            ("business_id", "businesses", False),
            ("service_id", "services", False),
        ),
        "page_image_assignments": (
            ("generated_page_id", "generated_pages", False),
            ("image_metadata_id", "image_metadata", False),
            ("website_id", "websites", True),
            ("site_plan_id", "site_plans", True),
            ("planned_page_id", "planned_pages", True),
            (
                "media_requirement_id",
                "planned_page_media_requirements",
                True,
            ),
            (
                "replaces_page_image_assignment_id",
                "page_image_assignments",
                True,
            ),
        ),
        "scoped_media_authorizations": (
            ("website_id", "websites", False),
            ("site_plan_id", "site_plans", False),
            ("planned_page_id", "planned_pages", False),
            ("generated_page_id", "generated_pages", True),
            (
                "media_requirement_id",
                "planned_page_media_requirements",
                False,
            ),
            ("image_metadata_id", "image_metadata", False),
            (
                "page_image_assignment_id",
                "page_image_assignments",
                True,
            ),
            (
                "supersedes_authorization_id",
                "scoped_media_authorizations",
                True,
            ),
        ),
        "approval_audits": (
            ("generated_page_id", "generated_pages", False),
        ),
        "page_revisions": (
            ("generated_page_id", "generated_pages", False),
        ),
        "generated_page_qa_results": (
            ("website_id", "websites", True),
            ("site_plan_id", "site_plans", True),
            ("planned_page_id", "planned_pages", True),
            ("generated_page_id", "generated_pages", False),
            (
                "latest_generated_page_revision_id",
                "page_revisions",
                True,
            ),
            ("page_composition_id", "page_compositions", True),
            (
                "supersedes_qa_result_id",
                "generated_page_qa_results",
                True,
            ),
        ),
        "wordpress_draft_audits": (
            ("generated_page_id", "generated_pages", False),
        ),
        "wordpress_heading_correction_audits": (("generated_page_id", "generated_pages", False),),
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
        "wordpress_metadata_states": (
            ("generated_page_id", "generated_pages", False),
        ),
        "wordpress_deployment_audits": (("generated_page_id", "generated_pages", False),),
        "wordpress_deployment_nonces": (("audit_id", "wordpress_deployment_audits", True),),
        "wordpress_deployment_transitions": (("audit_id", "wordpress_deployment_audits", False),),
        "wordpress_activation_audits": (
            ("generated_page_id", "generated_pages", False),
            ("installation_audit_id", "wordpress_deployment_audits", False),
        ),
        "wordpress_plugin_upgrade_audits": (
            ("generated_page_id", "generated_pages", False),
            ("installation_audit_id", "wordpress_deployment_audits", False),
            ("activation_audit_id", "wordpress_activation_audits", False),
        ),
        "wordpress_bootstrap_cleanup_audits": (
            ("generated_page_id", "generated_pages", False),
            ("installation_audit_id", "wordpress_deployment_audits", False),
            ("activation_audit_id", "wordpress_activation_audits", False),
            ("upgrade_audit_id", "wordpress_plugin_upgrade_audits", False),
        ),
        "wordpress_bootstrap_establishment_audits": (
            ("generated_page_id", "generated_pages", False),
            ("installation_audit_id", "wordpress_deployment_audits", False),
            ("activation_audit_id", "wordpress_activation_audits", False),
        ),
        "wordpress_metadata_lifecycle_audits": (
            ("generated_page_id", "generated_pages", False),
            ("installation_audit_id", "wordpress_deployment_audits", False),
            ("activation_audit_id", "wordpress_activation_audits", False),
        ),
        "wordpress_cache_aware_rendering_audits": (
            ("generated_page_id", "generated_pages", False),
            ("staging_audit_id", "wordpress_metadata_lifecycle_audits", False),
            ("recovery_disable_audit_id", "wordpress_metadata_lifecycle_audits", False),
        ),
        "wordpress_metadata_sync_audits": (
            ("generated_page_id", "generated_pages", False),
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


def _validate_brand_asset_ownership(data: dict[str, list[dict[str, Any]]]) -> None:
    """Reject cross-owner or malformed Brand Asset graphs before restore mutates state."""

    businesses = {record["id"]: record for record in data["businesses"]}
    brands = {record["id"]: record for record in data["brands"]}
    websites = {record["id"]: record for record in data["websites"]}
    identities = {record["id"]: record for record in data["website_identities"]}
    assets = {record["id"]: record for record in data["brand_assets"]}
    slot_contracts = {
        "header_logo": ({"primary_logo", "alternate_logo", "brand_mark"}, "website_header"),
        "footer_logo": ({"primary_logo", "alternate_logo", "brand_mark"}, "website_footer"),
        "favicon": ({"favicon"}, "browser_tab"),
        "browser_icon": ({"browser_icon"}, "browser_tab"),
        "apple_touch_icon": ({"apple_touch_icon"}, "browser_tab"),
        "open_graph_image": ({"open_graph_image"}, "social_preview"),
    }

    for asset in assets.values():
        brand = brands[asset["brand_id"]]
        if asset["business_id"] not in businesses or brand["business_id"] != asset["business_id"]:
            raise BackupValidationError(
                "Backup Brand Asset crosses a Business or Brand ownership boundary."
            )
        replacement_id = asset.get("replaces_brand_asset_id")
        if replacement_id is None:
            if asset["version"] != 1:
                raise BackupValidationError(
                    "Backup root Brand Asset must begin at version 1."
                )
            continue
        replacement = assets[replacement_id]
        if (
            replacement["business_id"] != asset["business_id"]
            or replacement["brand_id"] != asset["brand_id"]
            or replacement["asset_key"] != asset["asset_key"]
            or not isinstance(asset.get("version"), int)
            or not isinstance(replacement.get("version"), int)
            or asset["version"] != replacement["version"] + 1
        ):
            raise BackupValidationError(
                "Backup Brand Asset replacement crosses ownership, changes its asset key, or does not increase the version."
            )

    for assignment in data["website_identity_asset_assignments"]:
        identity = identities[assignment["website_identity_id"]]
        website = websites[assignment["website_id"]]
        brand = brands[assignment["brand_id"]]
        asset = assets[assignment["brand_asset_id"]]
        if (
            identity["website_id"] != assignment["website_id"]
            or website.get("brand_id") != assignment["brand_id"]
            or brand["business_id"] != website["business_id"]
            or asset["business_id"] != website["business_id"]
            or asset["brand_id"] != assignment["brand_id"]
        ):
            raise BackupValidationError(
                "Backup Website Identity asset selection crosses a Website, Business, or Brand ownership boundary."
            )
        allowed_types, required_usage = slot_contracts[assignment["slot"]]
        if (
            asset["asset_type"] not in allowed_types
            or required_usage not in asset["approved_usage"]
            or required_usage in asset["restrictions"]
        ):
            raise BackupValidationError(
                "Backup Website Identity asset selection violates its slot type, usage, or restriction contract."
            )
        if not str(asset.get("approved_by") or "").strip() or asset.get("approved_at") is None:
            raise BackupValidationError(
                "Backup Website Identity asset selection does not reference an approved-at-assignment asset."
            )
        approved_at = _datetime_value(asset["approved_at"], "brand_assets.approved_at")
        assigned_at = _datetime_value(
            assignment["assigned_at"],
            "website_identity_asset_assignments.assigned_at",
        )
        if _comparable_datetime(approved_at) > _comparable_datetime(assigned_at):
            raise BackupValidationError(
                "Backup Website Identity asset selection predates Brand Asset approval."
            )
        if assignment["status"] == "active" and asset["status"] != "approved":
            raise BackupValidationError(
                "Backup active Website Identity asset selection does not reference a currently approved asset."
            )


def _validate_theme_ownership(data: dict[str, list[dict[str, Any]]]) -> None:
    """Reject cross-Website Theme, selection, and composition binding graphs."""

    brands = {record["id"]: record for record in data["brands"]}
    websites = {record["id"]: record for record in data["websites"]}
    themes = {record["id"]: record for record in data["themes"]}
    selections = {
        record["id"]: record for record in data["website_theme_selections"]
    }
    for theme in themes.values():
        website = websites[theme["website_id"]]
        brand = brands[theme["brand_id"]]
        if (
            theme["business_id"] != website["business_id"]
            or website.get("brand_id") != theme["brand_id"]
            or brand["business_id"] != theme["business_id"]
        ):
            raise BackupValidationError(
                "Backup Theme crosses a Website, Business, or Brand ownership boundary."
            )
        replacement_id = theme.get("replaces_theme_id")
        if replacement_id is None:
            if theme["version"] != 1:
                raise BackupValidationError(
                    "Backup root Theme must begin at version 1."
                )
            continue
        replacement = themes[replacement_id]
        if (
            replacement["website_id"] != theme["website_id"]
            or replacement["business_id"] != theme["business_id"]
            or replacement["brand_id"] != theme["brand_id"]
            or replacement["theme_key"] != theme["theme_key"]
            or theme["version"] != replacement["version"] + 1
        ):
            raise BackupValidationError(
                "Backup Theme replacement crosses ownership, changes its key, or does not increase the version."
            )

    for selection in selections.values():
        theme = themes[selection["theme_id"]]
        if theme["website_id"] != selection["website_id"]:
            raise BackupValidationError(
                "Backup Website Theme selection crosses a Website ownership boundary."
            )
        if selection["status"] == "active" and (
            theme["lifecycle_status"] != "available"
            or theme["approval_status"] != "approved"
        ):
            raise BackupValidationError(
                "Backup active Website Theme selection does not reference an approved available Theme."
            )

    for composition in data["page_compositions"]:
        source_snapshot = composition.get("source_snapshot")
        if not isinstance(source_snapshot, dict):
            raise BackupValidationError(
                "Backup Page Composition source snapshot must be an object."
            )
        binding = source_snapshot.get("theme")
        if binding is None:
            continue
        if not isinstance(binding, dict):
            raise BackupValidationError(
                "Backup Page Composition Theme binding must be an object."
            )
        if binding.get("website_id") != composition["website_id"]:
            raise BackupValidationError(
                "Backup Page Composition Theme binding crosses a Website boundary."
            )
        theme_id = binding.get("theme_id")
        if theme_id is not None:
            theme = themes.get(theme_id)
            if not theme or theme["website_id"] != composition["website_id"]:
                raise BackupValidationError(
                    "Backup Page Composition references an unknown or cross-Website Theme."
                )
            if (
                binding.get("mode") != "selected"
                or binding.get("theme_key") != theme["theme_key"]
                or binding.get("theme_version") != theme["version"]
                or binding.get("token_contract_version")
                != theme["token_contract_version"]
                or binding.get("token_hash_sha256")
                != theme["token_hash_sha256"]
            ):
                raise BackupValidationError(
                    "Backup Page Composition Theme binding does not match its exact governed Theme identity."
                )
        else:
            from app.services.themes import (
                DEFAULT_THEME_TOKENS,
                SUPPORTED_TOKEN_CONTRACT_VERSION,
                canonical_token_hash,
            )

            if (
                binding.get("mode") != "neutral_fallback"
                or binding.get("theme_key") != "atlas-neutral"
                or binding.get("theme_version") != 1
                or binding.get("token_contract_version")
                != SUPPORTED_TOKEN_CONTRACT_VERSION
                or binding.get("token_hash_sha256")
                != canonical_token_hash(DEFAULT_THEME_TOKENS)
                or binding.get("selection_id") is not None
                or binding.get("selection_version") is not None
            ):
                raise BackupValidationError(
                    "Backup Page Composition neutral Theme binding is not the exact deterministic fallback identity."
                )
        selection_id = binding.get(
            "selection_id", binding.get("theme_selection_id")
        )
        if selection_id is not None:
            selection = selections.get(selection_id)
            if (
                not selection
                or selection["website_id"] != composition["website_id"]
                or (theme_id is not None and selection["theme_id"] != theme_id)
            ):
                raise BackupValidationError(
                    "Backup Page Composition references an unknown or cross-Website Theme selection."
                )
            if binding.get("selection_version") != selection["version"]:
                raise BackupValidationError(
                    "Backup Page Composition Theme binding does not match its exact selection version."
                )
        elif theme_id is not None:
            raise BackupValidationError(
                "Backup Page Composition governed Theme binding lacks its selection identity."
            )


def _validate_page_media_ownership(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    """Reject malformed or cross-scope page-media governance before restore."""

    businesses = {record["id"]: record for record in data["businesses"]}
    websites = {record["id"]: record for record in data["websites"]}
    site_plans = {record["id"]: record for record in data["site_plans"]}
    planned_pages = {record["id"]: record for record in data["planned_pages"]}
    generated_pages = {record["id"]: record for record in data["generated_pages"]}
    services = {record["id"]: record for record in data["services"]}
    planning_records = {
        record["id"]: record for record in data["website_media_planning_records"]
    }
    requirements = {
        record["id"]: record for record in data["planned_page_media_requirements"]
    }
    images = {record["id"]: record for record in data["image_metadata"]}
    assignments = {record["id"]: record for record in data["page_image_assignments"]}
    authorizations = {
        record["id"]: record for record in data["scoped_media_authorizations"]
    }

    v2_requirement_planning_ids = {
        record.get("planning_record_id")
        for record in requirements.values()
        if isinstance(record.get("contract_version"), int)
        and record["contract_version"] >= 2
    }

    active_requirements: set[tuple[int, str]] = set()
    active_requirement_targets: set[tuple[int, str]] = set()
    for record in planning_records.values():
        website = websites[record["website_id"]]
        plan = site_plans[record["site_plan_id"]]
        if (
            record["business_id"] not in businesses
            or website["business_id"] != record["business_id"]
            or plan["website_id"] != record["website_id"]
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or not str(record.get("algorithm_version") or "").strip()
            or not _is_lower_sha256(record.get("source_hash"))
            or not isinstance(record.get("generated_media_suggestions"), list)
            or not isinstance(record.get("source_snapshot"), dict)
        ):
            raise BackupValidationError(
                "Backup Page Media planning record crosses a Website, Business, or Site Plan boundary or is malformed."
            )
        _datetime_value(
            record.get("generated_at"),
            "website_media_planning_records.generated_at",
        )
        snapshot = record["source_snapshot"]
        if (
            snapshot.get("website_id") != record["website_id"]
            or snapshot.get("site_plan_id") != record["site_plan_id"]
            or snapshot.get("algorithm_version") != record["algorithm_version"]
            or _canonical_json_hash(snapshot) != record["source_hash"]
            or not isinstance(snapshot.get("planned_pages"), list)
        ):
            raise BackupValidationError(
                "Backup Page Media planning source snapshot is stale, malformed, or out of scope."
            )
        claims_v2_contract = (
            str(record.get("algorithm_version") or "").endswith("-v2")
            or (
                isinstance(snapshot.get("placement_contract_version"), int)
                and snapshot["placement_contract_version"] >= 2
            )
            or any(
                isinstance(suggestion, dict)
                and isinstance(suggestion.get("contract_version"), int)
                and suggestion["contract_version"] >= 2
                for suggestion in record["generated_media_suggestions"]
            )
            or record["id"] in v2_requirement_planning_ids
        )
        if claims_v2_contract and (
            not str(record.get("algorithm_version") or "").endswith("-v2")
            or snapshot.get("placement_contract_version") != 2
            or not _is_lower_sha256(snapshot.get("placement_contract_manifest_hash"))
        ):
            raise BackupValidationError(
                "Backup V2 Page Media planning snapshot lacks its exact contract manifest identity."
            )
        snapshot_page_ids: set[int] = set()
        for snapshot_page in snapshot["planned_pages"]:
            if not isinstance(snapshot_page, dict):
                raise BackupValidationError(
                    "Backup Page Media planning source snapshot contains an invalid Planned Page."
                )
            page = planned_pages.get(snapshot_page.get("id"))
            if (
                not page
                or page["website_id"] != record["website_id"]
                or page["site_plan_id"] != record["site_plan_id"]
                or snapshot_page.get("service_id") != page.get("service_id")
                or snapshot_page.get("city_id") != page.get("city_id")
                or snapshot_page.get("county_id") != page.get("county_id")
                or snapshot_page.get("generated_page_id")
                != page.get("generated_page_id")
            ):
                raise BackupValidationError(
                    "Backup Page Media planning snapshot crosses a Planned Page relationship."
                )
            snapshot_page_ids.add(page["id"])
        suggestion_targets: set[tuple[int, str]] = set()
        for suggestion in record["generated_media_suggestions"]:
            if not isinstance(suggestion, dict):
                raise BackupValidationError(
                    "Backup Page Media suggestions must contain objects."
                )
            page = planned_pages.get(suggestion.get("planned_page_id"))
            if (
                not page
                or suggestion.get("website_id") != record["website_id"]
                or suggestion.get("business_id") != record["business_id"]
                or suggestion.get("site_plan_id") != record["site_plan_id"]
                or page["website_id"] != record["website_id"]
                or page["site_plan_id"] != record["site_plan_id"]
                or page["id"] not in snapshot_page_ids
                or not str(suggestion.get("suggestion_key") or "").strip()
                or not str(suggestion.get("placement_key") or "").strip()
                or not str(suggestion.get("component_or_section") or "").strip()
                or not isinstance(suggestion.get("contract_version"), int)
                or suggestion["contract_version"] < 1
                or (
                    suggestion["contract_version"] >= 2
                    and not str(
                        suggestion.get("target_component_instance_key") or ""
                    ).strip()
                )
            ):
                raise BackupValidationError(
                    "Backup Page Media suggestion crosses a Website, Business, Site Plan, or Planned Page boundary."
                )
            target_instance = str(
                suggestion.get("target_component_instance_key") or ""
            ).strip()
            if target_instance:
                target_key = (page["id"], target_instance)
                if target_key in suggestion_targets:
                    raise BackupValidationError(
                        "Backup Page Media suggestions duplicate an exact component-instance target."
                    )
                suggestion_targets.add(target_key)
        replacement_id = record.get("replaces_record_id")
        if replacement_id is None:
            if record["version"] != 1:
                raise BackupValidationError(
                    "Backup root Page Media planning record must begin at version 1."
                )
        else:
            replacement = planning_records[replacement_id]
            if (
                replacement["website_id"] != record["website_id"]
                or replacement["business_id"] != record["business_id"]
                or replacement["site_plan_id"] != record["site_plan_id"]
                or record["version"] != replacement["version"] + 1
            ):
                raise BackupValidationError(
                    "Backup Page Media planning replacement crosses ownership or skips a version."
                )

    for record in requirements.values():
        website = websites[record["website_id"]]
        plan = site_plans[record["site_plan_id"]]
        page = planned_pages[record["planned_page_id"]]
        planning = planning_records[record["planning_record_id"]]
        if (
            website["business_id"] != record["business_id"]
            or plan["website_id"] != record["website_id"]
            or page["website_id"] != record["website_id"]
            or page["site_plan_id"] != record["site_plan_id"]
            or planning["website_id"] != record["website_id"]
            or planning["business_id"] != record["business_id"]
            or planning["site_plan_id"] != record["site_plan_id"]
            or record.get("requirement_state")
            not in {"required", "advisory", "excluded", "deferred"}
            or record.get("lifecycle_status")
            not in {"active", "superseded", "retired"}
            or not isinstance(record.get("contract_version"), int)
            or record["contract_version"] < 1
            or not isinstance(record.get("version"), int)
            or record["version"] < 1
            or not _is_positive_int(record.get("minimum_width"))
            or not _is_positive_int(record.get("minimum_height"))
            or not all(
                str(record.get(field) or "").strip()
                for field in (
                    "component_or_section",
                    "placement_key",
                    "purpose",
                    "customer_outcome",
                    "intended_subject",
                    "orientation",
                    "aspect_ratio",
                    "decided_by",
                    "rationale",
                )
            )
            or not all(
                str(record.get(field) or "").strip()
                for field in (
                    "crop_intent",
                    "focal_point_intent",
                    "responsive_behavior",
                    "accessibility_intent",
                    "permitted_reuse_policy",
                    "replacement_policy",
                )
            )
            or not _is_nonempty_trimmed_string_list(
                record.get("approved_source_constraints")
            )
            or not isinstance(record.get("compatible_page_types"), list)
            or page.get("page_type") not in record["compatible_page_types"]
            or (
                record["contract_version"] >= 2
                and not str(
                    record.get("target_component_instance_key") or ""
                ).strip()
            )
        ):
            raise BackupValidationError(
                "Backup Planned Page media requirement is malformed or crosses a Website, Business, Site Plan, planning-record, or page boundary."
            )
        _datetime_value(
            record.get("decided_at"),
            "planned_page_media_requirements.decided_at",
        )
        source_key = record.get("source_suggestion_key")
        if source_key is not None and not any(
            suggestion.get("suggestion_key") == source_key
            and suggestion.get("planned_page_id") == record["planned_page_id"]
            and suggestion.get("placement_key") == record["placement_key"]
            and suggestion.get("contract_version") == record["contract_version"]
            and suggestion.get("component_or_section")
            == record["component_or_section"]
            and suggestion.get("target_component_instance_key")
            == record.get("target_component_instance_key")
            for suggestion in planning["generated_media_suggestions"]
        ):
            raise BackupValidationError(
                "Backup Planned Page media requirement references an unknown or out-of-scope suggestion."
            )
        replacement_id = record.get("replaces_requirement_id")
        if replacement_id is None:
            if record["version"] != 1:
                raise BackupValidationError(
                    "Backup root Planned Page media requirement must begin at version 1."
                )
        else:
            replacement = requirements[replacement_id]
            if (
                replacement["website_id"] != record["website_id"]
                or replacement["business_id"] != record["business_id"]
                or replacement["site_plan_id"] != record["site_plan_id"]
                or replacement["planned_page_id"] != record["planned_page_id"]
                or replacement["placement_key"] != record["placement_key"]
                or record["version"] != replacement["version"] + 1
            ):
                raise BackupValidationError(
                    "Backup Planned Page media requirement replacement crosses ownership, changes placement, or skips a version."
                )
        if record["lifecycle_status"] == "active":
            key = (record["planned_page_id"], record["placement_key"])
            if key in active_requirements:
                raise BackupValidationError(
                    "Backup contains multiple active media requirements for one Planned Page placement."
                )
            active_requirements.add(key)
            target_instance = str(
                record.get("target_component_instance_key") or ""
            ).strip()
            if target_instance:
                target_key = (record["planned_page_id"], target_instance)
                if target_key in active_requirement_targets:
                    raise BackupValidationError(
                        "Backup contains multiple active media requirements for one exact component instance."
                    )
                active_requirement_targets.add(target_key)

    governed_statuses = {
        "legacy_unverified",
        "pending_review",
        "approved",
        "rejected",
        "retired",
    }
    provenance_types = {
        "company_original",
        "commissioned",
        "licensed",
        "stock",
        "generated",
        "public_domain",
    }
    rights_statuses = {"owned", "commissioned", "licensed", "public_domain"}
    acquisition_sources = {
        "company_photograph",
        "commissioned",
        "licensed",
        "stock",
        "generated",
        "operator_upload",
        "public_domain",
    }
    acquisition_provenance = {
        "company_photograph": {"company_original"},
        "commissioned": {"commissioned"},
        "licensed": {"licensed"},
        "stock": {"stock", "licensed"},
        "generated": {"generated"},
        "operator_upload": provenance_types,
        "public_domain": {"public_domain"},
    }
    provenance_rights = {
        "company_original": {"owned"},
        "commissioned": {"commissioned", "owned"},
        "licensed": {"licensed"},
        "stock": {"licensed"},
        "generated": {"owned", "licensed"},
        "public_domain": {"public_domain"},
    }
    gps_statuses = {"absent", "stripped", "present_unverified", "verified_authorized"}
    media_settings = get_settings()
    for record in images.values():
        authorization_mode = record.get("usage_authorization_mode")
        if authorization_mode not in {"contract_default", "scoped_required"}:
            raise BackupValidationError(
                "Backup Image Metadata has an invalid usage-authorization mode."
            )
        if backup_version not in {"0.56", "0.57", "0.58"} and authorization_mode != "contract_default":
            raise BackupValidationError(
                "Legacy backups cannot claim scoped-required Image Metadata."
            )
        try:
            required_authorization_terms = normalize_scoped_media_required_terms(
                record.get("required_authorization_terms")
            )
        except ValueError as exc:
            raise BackupValidationError(
                "Backup Image Metadata has invalid required authorization terms."
            ) from exc
        if (
            record.get("required_authorization_terms")
            != required_authorization_terms
            or (
                authorization_mode == "contract_default"
                and required_authorization_terms
            )
            or (
                authorization_mode == "scoped_required"
                and not required_authorization_terms
            )
        ):
            raise BackupValidationError(
                "Backup Image Metadata usage-authorization mode and required terms are incoherent."
            )
        website_id = record.get("website_id")
        if website_id is not None and websites[website_id]["business_id"] != record["business_id"]:
            raise BackupValidationError(
                "Backup Image Metadata crosses a Website or Business ownership boundary."
            )
        service_id = record.get("service_id")
        if service_id is not None and services[service_id]["business_id"] != record["business_id"]:
            raise BackupValidationError(
                "Backup Image Metadata crosses a Service or Business ownership boundary."
            )
        status = record.get("governance_status", "legacy_unverified")
        if status not in governed_statuses:
            raise BackupValidationError(
                "Backup Image Metadata has an invalid governance status."
            )
        if status != "legacy_unverified":
            if (
                website_id is None
                or not str(record.get("media_key") or "").strip()
                or not _is_positive_int(record.get("media_version"))
                or record.get("acquisition_source") not in acquisition_sources
                or record.get("provenance_type") not in provenance_types
                or record.get("rights_status") not in rights_statuses
                or record.get("provenance_type")
                not in acquisition_provenance.get(
                    record.get("acquisition_source"),
                    set(),
                )
                or record.get("rights_status")
                not in provenance_rights.get(
                    record.get("provenance_type"),
                    set(),
                )
                or record.get("gps_metadata_status") not in gps_statuses
                or not all(
                    str(record.get(field) or "").strip()
                    for field in (
                        "managed_storage_path",
                        "creator_source_identity",
                        "created_by",
                        "provenance_notes",
                        "rights_holder",
                        "rights_notes",
                        "accessibility_intent",
                        "mime_type",
                        "original_filename",
                        "stored_filename",
                    )
                )
                or not _is_positive_int(record.get("file_size"))
                or not _is_positive_int(record.get("width"))
                or not _is_positive_int(record.get("height"))
                or not _is_lower_sha256(record.get("checksum_sha256"))
                or not all(
                    _is_nonempty_normalized_string_list(record.get(field))
                    for field in (
                        "approved_usage",
                        "prohibited_usage",
                        "permitted_placement_keys",
                    )
                )
                or set(record["approved_usage"]) & set(record["prohibited_usage"])
                or not _is_safe_backup_filename(record.get("stored_filename"))
                or not _is_safe_backup_filename(record.get("original_filename"))
                or record.get("mime_type") not in BRAND_ASSET_MIME_EXTENSIONS
                or Path(record["original_filename"]).suffix.lower()
                not in BRAND_ASSET_MIME_EXTENSIONS.get(record.get("mime_type"), set())
                or Path(record["stored_filename"]).suffix.lower()
                not in BRAND_ASSET_MIME_EXTENSIONS.get(record.get("mime_type"), set())
                or record.get("managed_storage_path")
                != f"originals/{record['stored_filename']}"
                or not _has_coherent_page_media_urls(
                    record,
                    record["stored_filename"],
                    str(media_settings.media_public_url),
                )
            ):
                raise BackupValidationError(
                    "Backup contains incomplete or invalid governed page-media provenance, rights, binary identity, usage, or accessibility data."
                )
        if status in {"approved", "retired"}:
            if (
                not _is_positive_int(record.get("approval_version"))
                or not str(record.get("approved_by") or "").strip()
                or record.get("approved_at") is None
            ):
                raise BackupValidationError(
                    "Backup governed page media lacks approval provenance."
                )
            _datetime_value(record["approved_at"], "image_metadata.approved_at")
        if status == "retired":
            if (
                not str(record.get("retired_by") or "").strip()
                or not str(record.get("retirement_rationale") or "").strip()
                or record.get("retired_at") is None
            ):
                raise BackupValidationError(
                    "Backup retired page media lacks retirement provenance."
                )
            _datetime_value(record["retired_at"], "image_metadata.retired_at")
        if record.get("gps_metadata_status") == "verified_authorized":
            if (
                record.get("acquisition_source") != "company_photograph"
                or not isinstance(record.get("gps_metadata"), dict)
                or not str(record.get("gps_authorized_by") or "").strip()
                or record.get("gps_authorized_at") is None
                or not str(record.get("gps_authorization_notes") or "").strip()
            ):
                raise BackupValidationError(
                    "Backup verified GPS metadata lacks legitimate-company-photo authorization."
                )
            _datetime_value(
                record["gps_authorized_at"], "image_metadata.gps_authorized_at"
            )
        if record.get("acquisition_source") in {"generated", "stock"} and record.get(
            "gps_metadata_status"
        ) not in {None, "absent", "stripped"}:
            raise BackupValidationError(
                "Backup generated or stock media improperly preserves GPS metadata."
            )
        replacement_id = record.get("replaces_image_metadata_id")
        if replacement_id is None:
            if status != "legacy_unverified" and record.get("media_version") != 1:
                raise BackupValidationError(
                    "Backup root governed page media must begin at version 1."
                )
        else:
            replacement = images[replacement_id]
            if (
                replacement["business_id"] != record["business_id"]
                or replacement.get("website_id") != website_id
                or replacement.get("media_key") != record.get("media_key")
                or not isinstance(replacement.get("media_version"), int)
                or record.get("media_version") != replacement["media_version"] + 1
            ):
                raise BackupValidationError(
                    "Backup governed page-media replacement crosses ownership, changes its key, or skips a version."
                )

    active_assignments: set[int] = set()
    governance_fields = (
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "media_requirement_id",
        "assignment_version",
        "media_version",
        "placement_contract_version",
        "assigned_by",
        "assignment_rationale",
        "assigned_at",
    )
    for record in assignments.values():
        assignment_status = record.get("status", "active")
        if assignment_status not in {"active", "replaced", "retired"}:
            raise BackupValidationError(
                "Backup Page Image Assignment has an invalid lifecycle status."
            )
        if assignment_status == "replaced":
            if (
                not str(record.get("replaced_by") or "").strip()
                or not str(record.get("replacement_rationale") or "").strip()
                or record.get("replaced_at") is None
            ):
                raise BackupValidationError(
                    "Backup replaced Page Image Assignment lacks replacement provenance."
                )
            _datetime_value(
                record["replaced_at"], "page_image_assignments.replaced_at"
            )
        if assignment_status == "retired":
            if (
                not str(record.get("retired_by") or "").strip()
                or not str(record.get("retirement_rationale") or "").strip()
                or record.get("retired_at") is None
            ):
                raise BackupValidationError(
                    "Backup retired Page Image Assignment lacks retirement provenance."
                )
            _datetime_value(
                record["retired_at"], "page_image_assignments.retired_at"
            )
        populated = [record.get(field) is not None for field in governance_fields]
        if any(populated) and not all(populated):
            raise BackupValidationError(
                "Backup Page Image Assignment has partial governed binding provenance."
            )
        if not any(populated):
            if record.get("replaces_page_image_assignment_id") is not None:
                raise BackupValidationError(
                    "Backup legacy Page Image Assignment cannot claim a governed replacement."
                )
            continue
        website = websites[record["website_id"]]
        plan = site_plans[record["site_plan_id"]]
        page = planned_pages[record["planned_page_id"]]
        generated = generated_pages[record["generated_page_id"]]
        requirement = requirements[record["media_requirement_id"]]
        image = images[record["image_metadata_id"]]
        if (
            plan["website_id"] != record["website_id"]
            or page["website_id"] != record["website_id"]
            or page["site_plan_id"] != record["site_plan_id"]
            or page.get("generated_page_id") != record["generated_page_id"]
            or generated.get("website_id") != record["website_id"]
            or generated.get("business_id") != website["business_id"]
            or requirement["website_id"] != record["website_id"]
            or requirement["business_id"] != website["business_id"]
            or requirement["site_plan_id"] != record["site_plan_id"]
            or requirement["planned_page_id"] != record["planned_page_id"]
            or image.get("website_id") != record["website_id"]
            or image["business_id"] != website["business_id"]
            or image.get("media_version") != record["media_version"]
            or requirement["contract_version"]
            != record["placement_contract_version"]
            or not _is_positive_int(record.get("assignment_version"))
        ):
            raise BackupValidationError(
                "Backup governed Page Image Assignment crosses a Website, Business, Site Plan, Planned Page, requirement, draft, or media boundary."
            )
        try:
            effective_assignment_display_preset(
                record,
                requirement=requirement,
            )
        except DisplayPresetError as exc:
            raise BackupValidationError(
                f"Backup governed Page Image Assignment has an invalid display preset: {exc}"
            ) from exc
        _datetime_value(record["assigned_at"], "page_image_assignments.assigned_at")
        if record["status"] == "active":
            if (
                record["media_requirement_id"] in active_assignments
                or requirement["lifecycle_status"] != "active"
                or requirement["requirement_state"] not in {"required", "advisory"}
                or image.get("governance_status") != "approved"
            ):
                raise BackupValidationError(
                    "Backup active Page Image Assignment is duplicate, stale, disallowed, or references unapproved media."
                )
            active_assignments.add(record["media_requirement_id"])
        replacement_id = record.get("replaces_page_image_assignment_id")
        if replacement_id is None:
            if record["assignment_version"] != 1:
                raise BackupValidationError(
                    "Backup root governed Page Image Assignment must begin at version 1."
                )
        else:
            replacement = assignments[replacement_id]
            if (
                replacement.get("website_id") != record["website_id"]
                or replacement.get("site_plan_id") != record["site_plan_id"]
                or replacement.get("planned_page_id") != record["planned_page_id"]
                or replacement.get("media_requirement_id")
                != record["media_requirement_id"]
                or not isinstance(replacement.get("assignment_version"), int)
                or record["assignment_version"]
                != replacement["assignment_version"] + 1
            ):
                raise BackupValidationError(
                    "Backup Page Image Assignment replacement crosses ownership, changes its requirement, or skips a version."
                )

    for composition in data["page_compositions"]:
        snapshot = composition.get("source_snapshot")
        if not isinstance(snapshot, dict):
            raise BackupValidationError(
                "Backup Page Composition source snapshot must be an object."
            )
        if _canonical_json_hash(snapshot) != composition.get("source_hash"):
            raise BackupValidationError(
                "Backup Page Composition source hash does not match its exact snapshot."
            )
        page_media = snapshot.get("page_media")
        if page_media is None:
            continue
        if not isinstance(page_media, dict):
            raise BackupValidationError(
                "Backup Page Composition Page Media binding must be an object."
            )
        source_requirements = page_media.get("requirements")
        source_assignments = page_media.get("assignments")
        if not isinstance(source_requirements, list) or not isinstance(
            source_assignments, list
        ):
            raise BackupValidationError(
                "Backup Page Composition Page Media requirements and assignments must be lists."
            )
        bound_requirement_ids: set[int] = set()
        for binding in source_requirements:
            if not isinstance(binding, dict):
                raise BackupValidationError(
                    "Backup Page Composition Page Media requirement binding is malformed."
                )
            requirement = requirements.get(binding.get("id"))
            if (
                requirement is None
                or requirement["website_id"] != composition["website_id"]
                or requirement["site_plan_id"] != composition["site_plan_id"]
                or requirement["planned_page_id"] != composition["planned_page_id"]
                or binding.get("planning_record_id")
                != requirement["planning_record_id"]
                or binding.get("version") != requirement["version"]
                or binding.get("contract_version")
                != requirement["contract_version"]
                or binding.get("component_or_section")
                != requirement["component_or_section"]
                or binding.get("target_component_instance_key")
                != requirement.get("target_component_instance_key")
                or not _is_positive_int(binding.get("component_contract_version"))
                or binding.get("lifecycle_status")
                != requirement["lifecycle_status"]
            ):
                raise BackupValidationError(
                    "Backup Page Composition Page Media requirement crosses scope or loses its exact contract identity."
                )
            if requirement["id"] in bound_requirement_ids:
                raise BackupValidationError(
                    "Backup Page Composition duplicates a Page Media requirement binding."
                )
            bound_requirement_ids.add(requirement["id"])
        for binding in source_assignments:
            if not isinstance(binding, dict):
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment binding is malformed."
                )
            requirement = requirements.get(binding.get("requirement_id"))
            if (
                requirement is None
                or requirement["id"] not in bound_requirement_ids
                or requirement["planned_page_id"] != composition["planned_page_id"]
                or binding.get("requirement_version") != requirement["version"]
                or binding.get("placement_contract_version")
                != requirement["contract_version"]
                or binding.get("target_component_instance_key")
                != requirement.get("target_component_instance_key")
            ):
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment loses its requirement identity."
                )
            assignment_id = binding.get("assignment_id")
            asset_id = binding.get("asset_id")
            if assignment_id is None:
                if asset_id is not None:
                    raise BackupValidationError(
                        "Backup Page Composition has an asset without a governed assignment."
                    )
                if any(
                    field in binding
                    for field in (
                        "authorization_id",
                        "authorization_version",
                        "authorization_fingerprint",
                        "authorization_terms",
                        "reuse_policy",
                        "authorization_assignment_id",
                        "authorization_assignment_version",
                    )
                ):
                    raise BackupValidationError(
                        "Backup Page Composition has scoped authorization evidence without an assignment."
                    )
                continue
            assignment = assignments.get(assignment_id)
            if (
                assignment is None
                or assignment.get("media_requirement_id") != requirement["id"]
                or assignment.get("planned_page_id")
                != composition["planned_page_id"]
                or assignment.get("generated_page_id")
                != composition["generated_page_id"]
                or assignment.get("image_metadata_id") != asset_id
                or binding.get("assignment_version")
                != assignment.get("assignment_version")
                or binding.get("media_version") != assignment.get("media_version")
            ):
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment crosses scope or loses its exact version identity."
                )
            try:
                effective_display_preset = effective_assignment_display_preset(
                    assignment,
                    requirement=requirement,
                )
            except DisplayPresetError as exc:
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment has an invalid "
                    f"display preset: {exc}"
                ) from exc
            has_stored_preset = "stored_display_preset" in binding
            has_effective_preset = "effective_display_preset" in binding
            if has_stored_preset != has_effective_preset:
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment has partial "
                    "display-preset diagnostics."
                )
            if has_stored_preset and (
                binding.get("stored_display_preset")
                != assignment.get("display_preset")
                or binding.get("effective_display_preset")
                != effective_display_preset
            ):
                raise BackupValidationError(
                    "Backup Page Composition Page Media assignment display-preset "
                    "diagnostics do not match the stored assignment and exact contract."
                )
            _validate_composition_media_authorization_binding(
                binding,
                composition=composition,
                requirement=requirement,
                assignment=assignment,
                image=images[asset_id],
                authorizations=authorizations,
                backup_version=backup_version,
            )
        for component in composition.get("generated_components", []):
            if not isinstance(component, dict):
                raise BackupValidationError(
                    "Backup Page Composition generated component is malformed."
                )
            bindings = component.get("input_bindings") or {}
            if not isinstance(bindings, dict):
                raise BackupValidationError(
                    "Backup Page Composition generated component bindings are malformed."
                )
            requirement_id = bindings.get("media_requirement_id")
            if requirement_id is None:
                continue
            requirement = requirements.get(requirement_id)
            assignment_id = bindings.get("page_image_assignment_id")
            if (
                requirement is None
                or requirement_id not in bound_requirement_ids
                or requirement["planned_page_id"] != composition["planned_page_id"]
                or bindings.get("target_component_key")
                != requirement["component_or_section"]
                or (
                    requirement["contract_version"] >= 2
                    and (
                        bindings.get("target_component_instance_key")
                        != requirement.get("target_component_instance_key")
                        or bindings.get("placement_contract_version")
                        != requirement["contract_version"]
                    )
                )
                or (
                    assignment_id is not None
                    and (
                        assignment_id not in assignments
                        or assignments[assignment_id].get("media_requirement_id")
                        != requirement_id
                    )
                )
            ):
                raise BackupValidationError(
                    "Backup Page Composition generated media component crosses its governed placement binding."
                )

    if backup_version not in {"0.53", "0.54", "0.55", "0.56", "0.57", "0.58"} and (planning_records or requirements):
        raise BackupValidationError(
            "Legacy backup versions cannot claim Page Media planning governance."
        )


def _validate_composition_media_authorization_binding(
    binding: dict[str, Any],
    *,
    composition: dict[str, Any],
    requirement: dict[str, Any],
    assignment: dict[str, Any],
    image: dict[str, Any],
    authorizations: dict[int, dict[str, Any]],
    backup_version: str,
) -> None:
    """Validate optional exact authorization evidence in one media snapshot.

    Backups before 0.56 and unchanged contract-default snapshots do not contain
    these keys.  Preserve that historical shape exactly; when any authorization
    key is present, however, the complete immutable binding must be present and
    must point to the exact durable authorization and assignment versions.
    """

    fields = {
        "authorization_id",
        "authorization_version",
        "authorization_fingerprint",
        "authorization_terms",
        "reuse_policy",
        "authorization_assignment_id",
        "authorization_assignment_version",
    }
    present = fields.intersection(binding)
    if not present:
        if (
            backup_version in {"0.56", "0.57", "0.58"}
            and composition.get("status") == "current"
            and assignment.get("status") == "active"
            and image.get("usage_authorization_mode") == "scoped_required"
        ):
            raise BackupValidationError(
                "Backup current Page Composition omits required scoped-media authorization evidence."
            )
        return
    if present != fields or any(binding.get(field) is None for field in fields):
        raise BackupValidationError(
            "Backup Page Composition has partial scoped-media authorization evidence."
        )
    authorization = authorizations.get(binding["authorization_id"])
    if authorization is None:
        raise BackupValidationError(
            "Backup Page Composition references an unknown scoped-media authorization."
        )
    try:
        normalized_terms = normalize_scoped_media_authorization_terms(
            binding["authorization_terms"]
        )
    except ValueError as exc:
        raise BackupValidationError(
            "Backup Page Composition has invalid scoped-media authorization terms."
        ) from exc
    if (
        binding["authorization_terms"] != normalized_terms
        or authorization.get("media_requirement_id") != requirement.get("id")
        or authorization.get("requirement_version") != requirement.get("version")
        or authorization.get("placement_contract_version")
        != requirement.get("contract_version")
        or authorization.get("planned_page_id") != composition.get("planned_page_id")
        or authorization.get("generated_page_id") != composition.get("generated_page_id")
        or authorization.get("image_metadata_id") != image.get("id")
        or authorization.get("media_version") != assignment.get("media_version")
        or authorization.get("page_image_assignment_id") != assignment.get("id")
        or authorization.get("assignment_version")
        != assignment.get("assignment_version")
        or binding["authorization_assignment_id"] != assignment.get("id")
        or binding["authorization_assignment_version"]
        != assignment.get("assignment_version")
        or binding["authorization_version"]
        != authorization.get("authorization_version")
        or binding["authorization_fingerprint"]
        != authorization.get("authorization_fingerprint")
        or binding["authorization_terms"]
        != authorization.get("authorization_terms")
        or binding["reuse_policy"] != authorization.get("reuse_policy")
        or (
            composition.get("status") == "current"
            and authorization.get("lifecycle_status") != "current"
        )
    ):
        raise BackupValidationError(
            "Backup Page Composition scoped-media authorization loses its exact scope, version, policy, or assignment identity."
        )


def _validate_scoped_media_authorizations(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    """Validate exact authorization scope, approval, assignment, and lineage."""

    records = data["scoped_media_authorizations"]
    if backup_version not in {"0.56", "0.57", "0.58"}:
        if records:
            raise BackupValidationError(
                "Legacy backup versions cannot claim scoped-media authorizations."
            )
        return

    required_fields = {
        "id",
        "created_at",
        "updated_at",
        "website_id",
        "site_plan_id",
        "planned_page_id",
        "generated_page_id",
        "media_requirement_id",
        "requirement_version",
        "placement_key",
        "placement_contract_version",
        "image_metadata_id",
        "media_version",
        "asset_checksum_sha256",
        "approval_version",
        "asset_approved_by",
        "asset_approved_at",
        "approval_fingerprint",
        "page_image_assignment_id",
        "assignment_version",
        "reuse_policy",
        "authorization_terms",
        "authorized_by",
        "authorization_rationale",
        "authorized_at",
        "authorization_version",
        "authorization_fingerprint",
        "lifecycle_status",
        "supersedes_authorization_id",
    }
    term_allowlist = set(SCOPED_MEDIA_AUTHORIZATION_TERMS)
    websites = {record["id"]: record for record in data["websites"]}
    site_plans = {record["id"]: record for record in data["site_plans"]}
    planned_pages = {record["id"]: record for record in data["planned_pages"]}
    generated_pages = {record["id"]: record for record in data["generated_pages"]}
    requirements = {
        record["id"]: record
        for record in data["planned_page_media_requirements"]
    }
    images = {record["id"]: record for record in data["image_metadata"]}
    assignments = {record["id"]: record for record in data["page_image_assignments"]}
    records_by_id = {record["id"]: record for record in records}
    current_requirements: set[int] = set()
    fingerprints: set[str] = set()
    successor_targets: set[int] = set()
    current_asset_authorizations: dict[tuple[int, int], list[dict[str, Any]]] = {}

    for record in records:
        if not required_fields.issubset(record):
            raise BackupValidationError(
                "Backup scoped-media authorization is missing durable evidence."
            )
        website = websites[record["website_id"]]
        plan = site_plans[record["site_plan_id"]]
        page = planned_pages[record["planned_page_id"]]
        requirement = requirements[record["media_requirement_id"]]
        image = images[record["image_metadata_id"]]
        generated_id = record["generated_page_id"]
        generated = generated_pages.get(generated_id) if generated_id is not None else None
        if (
            plan.get("website_id") != record["website_id"]
            or page.get("website_id") != record["website_id"]
            or page.get("site_plan_id") != record["site_plan_id"]
            or page.get("generated_page_id") != generated_id
            or (
                generated_id is not None
                and (
                    generated is None
                    or generated.get("website_id") != record["website_id"]
                    or generated.get("business_id") != website.get("business_id")
                )
            )
            or requirement.get("website_id") != record["website_id"]
            or requirement.get("business_id") != website.get("business_id")
            or requirement.get("site_plan_id") != record["site_plan_id"]
            or requirement.get("planned_page_id") != record["planned_page_id"]
            or requirement.get("version") != record["requirement_version"]
            or requirement.get("placement_key") != record["placement_key"]
            or requirement.get("contract_version")
            != record["placement_contract_version"]
        ):
            raise BackupValidationError(
                "Backup scoped-media authorization crosses its exact page or requirement scope."
            )
        if (
            image.get("website_id") != record["website_id"]
            or image.get("business_id") != website.get("business_id")
            or image.get("media_version") != record["media_version"]
            or image.get("checksum_sha256") != record["asset_checksum_sha256"]
            or image.get("approval_version") != record["approval_version"]
            or image.get("approved_by") != record["asset_approved_by"]
            or image.get("approved_at") is None
            or image.get("governance_status") not in {"approved", "retired"}
        ):
            raise BackupValidationError(
                "Backup scoped-media authorization loses its exact approved asset identity."
            )
        approved_at = _datetime_value(
            record["asset_approved_at"],
            "scoped_media_authorizations.asset_approved_at",
        )
        image_approved_at = _datetime_value(
            image["approved_at"],
            "image_metadata.approved_at",
        )
        authorized_at = _datetime_value(
            record["authorized_at"],
            "scoped_media_authorizations.authorized_at",
        )
        _datetime_value(
            record["created_at"],
            "scoped_media_authorizations.created_at",
        )
        _datetime_value(
            record["updated_at"],
            "scoped_media_authorizations.updated_at",
        )
        if (
            _comparable_datetime(approved_at)
            != _comparable_datetime(image_approved_at)
            or _comparable_datetime(authorized_at) < _comparable_datetime(approved_at)
            or not _is_positive_int(record.get("requirement_version"))
            or not _is_positive_int(record.get("placement_contract_version"))
            or not _is_positive_int(record.get("media_version"))
            or not _is_positive_int(record.get("approval_version"))
            or not _is_positive_int(record.get("authorization_version"))
            or not str(record.get("placement_key") or "").strip()
            or not str(record.get("asset_approved_by") or "").strip()
            or not str(record.get("authorized_by") or "").strip()
            or not str(record.get("authorization_rationale") or "").strip()
            or record.get("lifecycle_status") not in {"current", "superseded"}
            or not _is_lower_sha256(record.get("asset_checksum_sha256"))
            or not _is_lower_sha256(record.get("approval_fingerprint"))
            or not _is_lower_sha256(record.get("authorization_fingerprint"))
        ):
            raise BackupValidationError(
                "Backup scoped-media authorization has malformed typed evidence."
            )
        terms = record.get("authorization_terms")
        if not isinstance(terms, list):
            raise BackupValidationError(
                "Backup scoped-media authorization terms must be a list."
            )
        try:
            normalized_terms = validate_scoped_media_authorization_policy_terms(
                record.get("reuse_policy"),
                terms,
                required_terms=image.get("required_authorization_terms", []),
            )
        except ValueError as exc:
            raise BackupValidationError(
                "Backup scoped-media authorization has incoherent policy or typed terms."
            ) from exc
        if terms != normalized_terms or not set(terms).issubset(term_allowlist):
            raise BackupValidationError(
                "Backup scoped-media authorization terms are not normalized."
            )
        try:
            expected_approval = scoped_media_approval_fingerprint(
                {
                    **record,
                    "asset_website_id": image.get("website_id"),
                    "asset_business_id": image.get("business_id"),
                    "usage_authorization_mode": image.get(
                        "usage_authorization_mode"
                    ),
                    "required_authorization_terms": image.get(
                        "required_authorization_terms"
                    ),
                }
            )
            expected_authorization = scoped_media_authorization_fingerprint(record)
        except (KeyError, TypeError, ValueError) as exc:
            raise BackupValidationError(
                "Backup scoped-media authorization fingerprint input is malformed."
            ) from exc
        if record["approval_fingerprint"] != expected_approval:
            raise BackupValidationError(
                "Backup scoped-media authorization approval fingerprint does not match."
            )
        if record["authorization_fingerprint"] != expected_authorization:
            raise BackupValidationError(
                "Backup scoped-media authorization fingerprint does not match."
            )
        if record["authorization_fingerprint"] in fingerprints:
            raise BackupValidationError(
                "Backup contains duplicate scoped-media authorization fingerprints."
            )
        fingerprints.add(record["authorization_fingerprint"])

        assignment_id = record["page_image_assignment_id"]
        assignment_version = record["assignment_version"]
        if (assignment_id is None) != (assignment_version is None):
            raise BackupValidationError(
                "Backup scoped-media authorization has a partial assignment binding."
            )
        if assignment_id is not None:
            assignment = assignments[assignment_id]
            if (
                not _is_positive_int(assignment_version)
                or generated_id is None
                or assignment.get("generated_page_id") != generated_id
                or assignment.get("website_id") != record["website_id"]
                or assignment.get("site_plan_id") != record["site_plan_id"]
                or assignment.get("planned_page_id") != record["planned_page_id"]
                or assignment.get("media_requirement_id")
                != record["media_requirement_id"]
                or assignment.get("image_metadata_id") != record["image_metadata_id"]
                or assignment.get("media_version") != record["media_version"]
                or assignment.get("assignment_version") != assignment_version
                or assignment.get("placement_contract_version")
                != record["placement_contract_version"]
            ):
                raise BackupValidationError(
                    "Backup scoped-media authorization loses its exact assignment binding."
                )
            if (
                record["lifecycle_status"] == "current"
                and assignment.get("status") != "active"
            ):
                raise BackupValidationError(
                    "Backup current scoped-media authorization binds an inactive assignment."
                )
        if (
            record["lifecycle_status"] == "current"
            and image.get("governance_status") != "approved"
        ):
            raise BackupValidationError(
                "Backup current scoped-media authorization binds non-approved media."
            )
        if record["lifecycle_status"] == "current":
            requirement_id = record["media_requirement_id"]
            if (
                requirement.get("lifecycle_status") != "active"
                or requirement.get("requirement_state")
                not in {"required", "advisory"}
            ):
                raise BackupValidationError(
                    "Backup current scoped-media authorization binds a stale or disallowed requirement."
                )
            if any(
                candidate.get("website_id") == image.get("website_id")
                and candidate.get("media_key") == image.get("media_key")
                and isinstance(candidate.get("media_version"), int)
                and candidate["media_version"] > image.get("media_version", 0)
                and (
                    candidate.get("governance_status") == "approved"
                    or candidate.get("approved_at") is not None
                )
                for candidate in images.values()
            ):
                raise BackupValidationError(
                    "Backup current scoped-media authorization binds a superseded asset version."
                )
            if requirement_id in current_requirements:
                raise BackupValidationError(
                    "Backup has multiple current authorizations for one requirement."
                )
            current_requirements.add(requirement_id)
            current_asset_authorizations.setdefault(
                (record["image_metadata_id"], record["media_version"]), []
            ).append(record)

        predecessor_id = record["supersedes_authorization_id"]
        if record["authorization_version"] == 1:
            if predecessor_id is not None:
                raise BackupValidationError(
                    "Backup root scoped-media authorization claims a predecessor."
                )
        elif predecessor_id is None:
            raise BackupValidationError(
                "Backup successor scoped-media authorization lacks lineage."
            )
        if predecessor_id is not None:
            if predecessor_id == record["id"] or predecessor_id in successor_targets:
                raise BackupValidationError(
                    "Backup scoped-media authorization lineage is self-referential or forked."
                )
            successor_targets.add(predecessor_id)

    for record in records:
        predecessor_id = record["supersedes_authorization_id"]
        if predecessor_id is None:
            continue
        predecessor = records_by_id[predecessor_id]
        if (
            predecessor["website_id"] != record["website_id"]
            or predecessor["site_plan_id"] != record["site_plan_id"]
            or predecessor["planned_page_id"] != record["planned_page_id"]
            or predecessor["media_requirement_id"] != record["media_requirement_id"]
            or predecessor["requirement_version"] != record["requirement_version"]
            or predecessor["placement_key"] != record["placement_key"]
            or predecessor["placement_contract_version"]
            != record["placement_contract_version"]
            or record["authorization_version"]
            != predecessor["authorization_version"] + 1
            or predecessor["lifecycle_status"] != "superseded"
            or _comparable_datetime(
                _datetime_value(
                    record["authorized_at"],
                    "scoped_media_authorizations.authorized_at",
                )
            )
            < _comparable_datetime(
                _datetime_value(
                    predecessor["authorized_at"],
                    "scoped_media_authorizations.authorized_at",
                )
            )
        ):
            raise BackupValidationError(
                "Backup scoped-media authorization lineage crosses scope, skips a version, or rewrites currentness."
            )

    records_by_requirement: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        records_by_requirement.setdefault(record["media_requirement_id"], []).append(
            record
        )
    for history in records_by_requirement.values():
        ordered = sorted(history, key=lambda item: item["authorization_version"])
        if [item["authorization_version"] for item in ordered] != list(
            range(1, len(ordered) + 1)
        ):
            raise BackupValidationError(
                "Backup scoped-media authorization lineage is incomplete."
            )
        for index, record in enumerate(ordered):
            expected_predecessor = ordered[index - 1]["id"] if index else None
            if record["supersedes_authorization_id"] != expected_predecessor:
                raise BackupValidationError(
                    "Backup scoped-media authorization lineage does not follow its exact predecessor chain."
                )
            if index < len(ordered) - 1 and record["lifecycle_status"] != "superseded":
                raise BackupValidationError(
                    "Backup scoped-media authorization current state is not the lineage tip."
                )
        current = [
            record for record in ordered if record["lifecycle_status"] == "current"
        ]
        if current and current[0]["id"] != ordered[-1]["id"]:
            raise BackupValidationError(
                "Backup scoped-media authorization current state is not the lineage tip."
            )

    for scoped_rows in current_asset_authorizations.values():
        for row in scoped_rows:
            terms = set(row["authorization_terms"])
            other_rows = [
                candidate
                for candidate in scoped_rows
                if candidate["media_requirement_id"] != row["media_requirement_id"]
            ]
            if (
                row["reuse_policy"] == "requirement_only" or "no_reuse" in terms
            ) and other_rows:
                raise BackupValidationError(
                    "Backup requirement-only/no-reuse authorization crosses another current scope."
                )
            if row["reuse_policy"] == "page_only" and any(
                candidate["planned_page_id"] != row["planned_page_id"]
                for candidate in other_rows
            ):
                raise BackupValidationError(
                    "Backup page-only authorization crosses another Planned Page."
                )


def _validate_bound_qa_projection(
    projection: dict[str, Any],
    durable: dict[str, Any],
    *,
    field: str,
) -> None:
    """Require every redundant QA projection field to match immutable evidence."""

    expected = {
        "qa_result_id": durable.get("id"),
        "page_id": durable.get("generated_page_id"),
        "website_id": durable.get("website_id"),
        "site_plan_id": durable.get("site_plan_id"),
        "planned_page_id": durable.get("planned_page_id"),
        "latest_generated_page_revision_id": durable.get(
            "latest_generated_page_revision_id"
        ),
        "content_hash": durable.get("content_hash"),
        "source_hash": durable.get("source_hash"),
        "page_composition_id": durable.get("page_composition_id"),
        "composition_version": durable.get("composition_version"),
        "composition_source_hash": durable.get("composition_source_hash"),
        "qa_algorithm_key": durable.get("qa_algorithm_key"),
        "qa_algorithm_version": durable.get("qa_algorithm_version"),
        "qa_ruleset_key": durable.get("qa_ruleset_key"),
        "qa_ruleset_version": durable.get("qa_ruleset_version"),
        "qa_ruleset_hash": durable.get("qa_ruleset_hash"),
        "readiness_status": durable.get("readiness_status"),
        "passed_count": durable.get("passed_count"),
        "warning_count": durable.get("warning_count"),
        "failed_count": durable.get("failed_count"),
        "checks": durable.get("check_payload"),
        "result_hash": durable.get("result_hash"),
        # A bound projection records the state when this evidence was current;
        # immutable Approval Audit snapshots remain valid after later QA runs.
        "lifecycle_status": "current",
        "currentness_status": "current_exact_identity_match",
        "currentness_reasons": [],
    }
    if set(projection) != set(expected) | {"checked_at"}:
        raise BackupValidationError(
            f"Backup {field} does not use the exact durable QA projection contract."
        )
    for key, value in expected.items():
        if projection.get(key) != value:
            raise BackupValidationError(
                f"Backup {field}.{key} does not match its durable QA result."
            )
    if _comparable_datetime(
        _datetime_value(projection.get("checked_at"), f"{field}.checked_at")
    ) != _comparable_datetime(
        _datetime_value(durable.get("evaluated_at"), f"{field}.evaluated_at")
    ):
        raise BackupValidationError(
            f"Backup {field}.checked_at does not match its durable QA result."
        )


def _validate_legacy_qa_projection(value: dict[str, Any], *, field: str) -> None:
    checks = value.get("checks")
    if (
        set(value) != LEGACY_QA_PROJECTION_FIELDS
        or type(value.get("page_id")) is not int
        or value.get("readiness_status") not in {"ready", "needs_review", "blocked"}
        or not isinstance(checks, list)
        or not all(isinstance(check, dict) for check in checks)
        or any(
            type(value.get(key)) is not int or value[key] < 0
            for key in ("passed_count", "warning_count", "failed_count")
        )
    ):
        raise BackupValidationError(
            f"Backup {field} is neither exact legacy nor bound QA evidence."
        )
    _datetime_value(value.get("checked_at"), f"{field}.checked_at")
    observed = {
        status: sum(check.get("status") == status for check in checks)
        for status in ("pass", "warning", "fail")
    }
    if (
        value["passed_count"] != observed["pass"]
        or value["warning_count"] != observed["warning"]
        or value["failed_count"] != observed["fail"]
    ):
        raise BackupValidationError(f"Backup {field} legacy QA counts are inconsistent.")


def _validate_candidate_qa_projection(
    value: dict[str, Any],
    *,
    data: dict[str, list[dict[str, Any]]],
    owner_page_id: Any,
    field: str,
) -> None:
    """Validate an exact, non-persisted QA result captured by an Approval Audit."""

    if (
        set(value) != CANDIDATE_QA_PROJECTION_FIELDS
        or value.get("qa_result_id") is not None
        or value.get("lifecycle_status") != "candidate"
        or value.get("currentness_status") != "candidate_not_persisted"
        or value.get("currentness_reasons") != []
        or not _is_positive_int(owner_page_id)
        or value.get("page_id") != owner_page_id
    ):
        raise BackupValidationError(
            f"Backup {field} does not use the exact candidate QA projection contract."
        )

    websites = {record["id"]: record for record in data["websites"]}
    site_plans = {record["id"]: record for record in data["site_plans"]}
    planned_pages = {record["id"]: record for record in data["planned_pages"]}
    generated_pages = {record["id"]: record for record in data["generated_pages"]}
    revisions = {record["id"]: record for record in data["page_revisions"]}
    compositions = {record["id"]: record for record in data["page_compositions"]}

    website_id = value.get("website_id")
    site_plan_id = value.get("site_plan_id")
    planned_page_id = value.get("planned_page_id")
    if not all(
        _is_positive_int(identity)
        for identity in (website_id, site_plan_id, planned_page_id)
    ):
        raise BackupValidationError(
            f"Backup {field} has an incomplete Website-scoped candidate identity."
        )
    website = websites.get(website_id)
    plan = site_plans.get(site_plan_id)
    planned_page = planned_pages.get(planned_page_id)
    generated_page = generated_pages.get(owner_page_id)
    if (
        website is None
        or plan is None
        or planned_page is None
        or generated_page is None
        or generated_page.get("website_id") != website_id
        or plan.get("website_id") != website_id
        or planned_page.get("website_id") != website_id
        or planned_page.get("site_plan_id") != site_plan_id
        or planned_page.get("generated_page_id") != owner_page_id
    ):
        raise BackupValidationError(
            f"Backup {field} crosses a Website, Site Plan, Planned Page, or draft boundary."
        )

    revision_id = value.get("latest_generated_page_revision_id")
    if revision_id is not None:
        revision = revisions.get(revision_id)
        if (
            not _is_positive_int(revision_id)
            or revision is None
            or revision.get("generated_page_id") != owner_page_id
            or revision.get("draft_hash_after") != value.get("content_hash")
        ):
            raise BackupValidationError(
                f"Backup {field} loses its exact revision identity."
            )

    composition_id = value.get("page_composition_id")
    composition_binding = (
        composition_id,
        value.get("composition_version"),
        value.get("composition_source_hash"),
    )
    if composition_id is None:
        if composition_binding != (None, None, None):
            raise BackupValidationError(
                f"Backup {field} has a partial composition identity."
            )
    else:
        composition = compositions.get(composition_id)
        if (
            not _is_positive_int(composition_id)
            or composition is None
            or composition.get("website_id") != website_id
            or composition.get("site_plan_id") != site_plan_id
            or composition.get("planned_page_id") != planned_page_id
            or composition.get("generated_page_id") != owner_page_id
            or not _is_positive_int(value.get("composition_version"))
            or not _is_lower_sha256(value.get("composition_source_hash"))
        ):
            raise BackupValidationError(
                f"Backup {field} composition binding crosses scope or is malformed."
            )

    checks = value.get("checks")
    if (
        not _is_lower_sha256(value.get("content_hash"))
        or not _is_lower_sha256(value.get("source_hash"))
        or not _is_lower_sha256(value.get("qa_ruleset_hash"))
        or not _is_lower_sha256(value.get("result_hash"))
        or value.get("readiness_status") not in {"ready", "needs_review", "blocked"}
        or not isinstance(checks, list)
        or not all(
            isinstance(check, dict)
            and check.get("status") in {"pass", "warning", "fail"}
            for check in checks
        )
        or any(
            type(value.get(count_field)) is not int or value[count_field] < 0
            for count_field in ("passed_count", "warning_count", "failed_count")
        )
        or any(
            not isinstance(value.get(identity_field), str)
            or not value[identity_field].strip()
            for identity_field in (
                "qa_algorithm_key",
                "qa_algorithm_version",
                "qa_ruleset_key",
                "qa_ruleset_version",
            )
        )
    ):
        raise BackupValidationError(f"Backup {field} has malformed candidate evidence.")

    observed_counts = {
        status: sum(check.get("status") == status for check in checks)
        for status in ("pass", "warning", "fail")
    }
    expected_readiness = (
        "blocked"
        if observed_counts["fail"]
        else "needs_review"
        if observed_counts["warning"]
        else "ready"
    )
    if (
        value["passed_count"] != observed_counts["pass"]
        or value["warning_count"] != observed_counts["warning"]
        or value["failed_count"] != observed_counts["fail"]
        or value["readiness_status"] != expected_readiness
    ):
        raise BackupValidationError(
            f"Backup {field} candidate QA outcome is internally inconsistent."
        )

    evaluated_at = _datetime_value(value.get("checked_at"), f"{field}.checked_at")
    expected_hash = qa_result_record_hash(
        _qa_hash_values_from_projection(value, evaluated_at=evaluated_at)
    )
    if value.get("result_hash") != expected_hash:
        raise BackupValidationError(
            f"Backup {field} candidate QA identity or outcome hash does not match."
        )


def _validate_generated_page_qa_results(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    """Validate immutable QA identity, outcome integrity, and lineage."""

    records = data["generated_page_qa_results"]
    if backup_version not in {"0.55", "0.56", "0.57", "0.58"}:
        if records:
            raise BackupValidationError(
                "Legacy backup versions cannot claim durable Generated Page QA results."
            )
        return

    websites = {record["id"]: record for record in data["websites"]}
    site_plans = {record["id"]: record for record in data["site_plans"]}
    planned_pages = {record["id"]: record for record in data["planned_pages"]}
    generated_pages = {record["id"]: record for record in data["generated_pages"]}
    revisions = {record["id"]: record for record in data["page_revisions"]}
    compositions = {record["id"]: record for record in data["page_compositions"]}
    records_by_id = {record["id"]: record for record in records}
    valid_lifecycle = {"current", "superseded", "historical_unbound"}
    valid_readiness = {"ready", "needs_review", "blocked"}
    current_pages: set[int] = set()
    superseded_targets: set[int] = set()

    for generated_page in generated_pages.values():
        projection = generated_page.get("qa_result")
        if not isinstance(projection, dict):
            continue
        qa_result_id = projection.get("qa_result_id")
        if qa_result_id is None:
            _validate_legacy_qa_projection(
                projection,
                field="generated_pages.qa_result",
            )
            continue
        durable = records_by_id.get(qa_result_id)
        if (
            durable is None
            or durable.get("generated_page_id") != generated_page.get("id")
            or durable.get("lifecycle_status") != "current"
        ):
            raise BackupValidationError(
                "Backup Generated Page QA projection references missing, stale, or cross-page durable evidence."
            )
        _validate_bound_qa_projection(
            projection,
            durable,
            field="generated_pages.qa_result",
        )
        if (
            generated_page.get("qa_status") != durable.get("readiness_status")
            or _comparable_datetime(
                _datetime_value(
                    generated_page.get("qa_checked_at"),
                    "generated_pages.qa_checked_at",
                )
            )
            != _comparable_datetime(
                _datetime_value(
                    durable.get("evaluated_at"),
                    "generated_page_qa_results.evaluated_at",
                )
            )
        ):
            raise BackupValidationError(
                "Backup Generated Page QA status or timestamp diverges from durable evidence."
            )

    for audit in data["approval_audits"]:
        snapshot = audit.get("qa_result_snapshot")
        if not isinstance(snapshot, dict):
            continue
        qa_result_id = snapshot.get("qa_result_id")
        if qa_result_id is None:
            if set(snapshot) == LEGACY_QA_PROJECTION_FIELDS:
                _validate_legacy_qa_projection(
                    snapshot,
                    field="approval_audits.qa_result_snapshot",
                )
            else:
                _validate_candidate_qa_projection(
                    snapshot,
                    data=data,
                    owner_page_id=audit.get("generated_page_id"),
                    field="approval_audits.qa_result_snapshot",
                )
                if (
                    audit.get("qa_status_at_approval")
                    != snapshot.get("readiness_status")
                    or audit.get("draft_hash_at_approval")
                    != snapshot.get("content_hash")
                    or _comparable_datetime(
                        _datetime_value(
                            audit.get("qa_checked_at"),
                            "approval_audits.qa_checked_at",
                        )
                    )
                    != _comparable_datetime(
                        _datetime_value(
                            snapshot.get("checked_at"),
                            "approval_audits.qa_result_snapshot.checked_at",
                        )
                    )
                ):
                    raise BackupValidationError(
                        "Backup Approval Audit QA status, content, or timestamp diverges from candidate evidence."
                    )
            continue
        durable = records_by_id.get(qa_result_id)
        if (
            durable is None
            or durable.get("generated_page_id") != audit.get("generated_page_id")
        ):
            raise BackupValidationError(
                "Backup Approval Audit QA snapshot references missing or cross-page durable evidence."
            )
        _validate_bound_qa_projection(
            snapshot,
            durable,
            field="approval_audits.qa_result_snapshot",
        )
        if (
            audit.get("qa_status_at_approval") != durable.get("readiness_status")
            or _comparable_datetime(
                _datetime_value(
                    audit.get("qa_checked_at"),
                    "approval_audits.qa_checked_at",
                )
            )
            != _comparable_datetime(
                _datetime_value(
                    durable.get("evaluated_at"),
                    "generated_page_qa_results.evaluated_at",
                )
            )
        ):
            raise BackupValidationError(
                "Backup Approval Audit QA status or timestamp diverges from durable evidence."
            )

    for record in records:
        lifecycle = record.get("lifecycle_status")
        generated_page = generated_pages.get(record.get("generated_page_id"))
        if lifecycle not in valid_lifecycle or generated_page is None:
            raise BackupValidationError(
                "Backup Generated Page QA result has invalid lifecycle or page identity."
            )
        if not _is_lower_sha256(record.get("result_hash")):
            raise BackupValidationError(
                "Backup Generated Page QA result has an invalid result hash."
            )
        _datetime_value(
            record.get("created_at"),
            "generated_page_qa_results.created_at",
        )
        _datetime_value(
            record.get("updated_at"),
            "generated_page_qa_results.updated_at",
        )

        supersedes_id = record.get("supersedes_qa_result_id")
        if supersedes_id is not None:
            superseded = records_by_id.get(supersedes_id)
            if (
                superseded is None
                or supersedes_id == record.get("id")
                or superseded.get("generated_page_id")
                != record.get("generated_page_id")
                or superseded.get("lifecycle_status") != "superseded"
                or supersedes_id in superseded_targets
            ):
                raise BackupValidationError(
                    "Backup Generated Page QA supersession lineage is invalid or branched."
                )
            superseded_targets.add(supersedes_id)

        if lifecycle == "historical_unbound":
            historical_payload = record.get("historical_payload")
            if not isinstance(historical_payload, dict):
                raise BackupValidationError(
                    "Backup historical QA evidence payload must be an object."
                )
            if supersedes_id is not None or record["result_hash"] != historical_qa_payload_hash(
                historical_payload
            ):
                raise BackupValidationError(
                    "Backup historical QA evidence payload or hash was altered."
                )
            continue

        website = websites.get(record.get("website_id"))
        plan = site_plans.get(record.get("site_plan_id"))
        planned_page = planned_pages.get(record.get("planned_page_id"))
        if (
            website is None
            or plan is None
            or planned_page is None
            or generated_page.get("website_id") != record.get("website_id")
            or plan.get("website_id") != record.get("website_id")
            or planned_page.get("website_id") != record.get("website_id")
            or planned_page.get("site_plan_id") != record.get("site_plan_id")
            or planned_page.get("generated_page_id")
            != record.get("generated_page_id")
        ):
            raise BackupValidationError(
                "Backup Generated Page QA result crosses a Website, Site Plan, Planned Page, or draft boundary."
            )

        revision_id = record.get("latest_generated_page_revision_id")
        if revision_id is not None:
            revision = revisions.get(revision_id)
            if (
                revision is None
                or revision.get("generated_page_id")
                != record.get("generated_page_id")
                or revision.get("draft_hash_after") != record.get("content_hash")
            ):
                raise BackupValidationError(
                    "Backup Generated Page QA result loses its exact revision identity."
                )

        composition_id = record.get("page_composition_id")
        composition_binding = (
            composition_id,
            record.get("composition_version"),
            record.get("composition_source_hash"),
        )
        if composition_id is None:
            if composition_binding != (None, None, None):
                raise BackupValidationError(
                    "Backup Generated Page QA result has a partial composition identity."
                )
        else:
            composition = compositions.get(composition_id)
            if (
                composition is None
                or composition.get("website_id") != record.get("website_id")
                or composition.get("site_plan_id") != record.get("site_plan_id")
                or composition.get("planned_page_id")
                != record.get("planned_page_id")
                or composition.get("generated_page_id")
                != record.get("generated_page_id")
                or not _is_positive_int(record.get("composition_version"))
                or not _is_lower_sha256(record.get("composition_source_hash"))
            ):
                raise BackupValidationError(
                    "Backup Generated Page QA composition binding crosses scope or is malformed."
                )

        checks = record.get("check_payload")
        if (
            not _is_lower_sha256(record.get("content_hash"))
            or not _is_lower_sha256(record.get("source_hash"))
            or not _is_lower_sha256(record.get("qa_ruleset_hash"))
            or record.get("readiness_status") not in valid_readiness
            or not isinstance(checks, list)
            or not all(isinstance(check, dict) for check in checks)
            or any(
                not isinstance(record.get(field), int) or record[field] < 0
                for field in ("passed_count", "warning_count", "failed_count")
            )
            or any(
                not isinstance(record.get(field), str) or not record[field].strip()
                for field in (
                    "qa_algorithm_key",
                    "qa_algorithm_version",
                    "qa_ruleset_key",
                    "qa_ruleset_version",
                )
            )
            or record.get("historical_payload") is not None
        ):
            raise BackupValidationError(
                "Backup Generated Page QA result has malformed bound evidence."
            )
        evaluated_at = _datetime_value(
            record.get("evaluated_at"),
            "generated_page_qa_results.evaluated_at",
        )
        observed_counts = {
            status: sum(check.get("status") == status for check in checks)
            for status in ("pass", "warning", "fail")
        }
        if (
            record["passed_count"] != observed_counts["pass"]
            or record["warning_count"] != observed_counts["warning"]
            or record["failed_count"] != observed_counts["fail"]
        ):
            raise BackupValidationError(
                "Backup Generated Page QA counts do not match the exact check payload."
            )
        hash_values = {**record, "evaluated_at": evaluated_at}
        if record["result_hash"] != qa_result_record_hash(hash_values):
            raise BackupValidationError(
                "Backup Generated Page QA identity or outcome hash does not match."
            )
        if lifecycle == "current":
            if record["generated_page_id"] in current_pages:
                raise BackupValidationError(
                    "Backup contains multiple current QA results for one Generated Page."
                )
            current_pages.add(record["generated_page_id"])

    for record in records:
        visited: set[int] = set()
        cursor = record
        while cursor.get("supersedes_qa_result_id") is not None:
            cursor_id = cursor["supersedes_qa_result_id"]
            if cursor_id in visited:
                raise BackupValidationError(
                    "Backup Generated Page QA supersession lineage contains a cycle."
                )
            visited.add(cursor_id)
            cursor = records_by_id[cursor_id]

    bound_by_page: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("lifecycle_status") in {"current", "superseded"}:
            bound_by_page.setdefault(record["generated_page_id"], []).append(record)
    for page_id, bound_records in bound_by_page.items():
        currents = [
            record
            for record in bound_records
            if record.get("lifecycle_status") == "current"
        ]
        if len(currents) != 1:
            raise BackupValidationError(
                "Backup bound QA lineage must have exactly one current result per Generated Page."
            )
        bound_ids = {record["id"] for record in bound_records}
        visited: set[int] = set()
        cursor = currents[0]
        while True:
            cursor_id = cursor["id"]
            if cursor_id in visited:
                raise BackupValidationError(
                    "Backup Generated Page QA supersession lineage contains a cycle."
                )
            visited.add(cursor_id)
            parent_id = cursor.get("supersedes_qa_result_id")
            if parent_id is None:
                break
            cursor = records_by_id[parent_id]
        if visited != bound_ids:
            raise BackupValidationError(
                "Backup bound QA lineage is disconnected or has a reversed lifecycle order."
            )

    for page_id in current_pages:
        generated_page = generated_pages[page_id]
        projection = generated_page.get("qa_result")
        current = next(
            record
            for record in records
            if record.get("generated_page_id") == page_id
            and record.get("lifecycle_status") == "current"
        )
        if projection is None:
            if (
                generated_page.get("qa_status") != "not_run"
                or generated_page.get("qa_checked_at") is not None
            ):
                raise BackupValidationError(
                    "Backup invalidated QA projection retains a status or timestamp."
                )
            continue
        if (
            not isinstance(projection, dict)
            or projection.get("qa_result_id") != current.get("id")
            or projection.get("page_id") != page_id
            or projection.get("result_hash") != current.get("result_hash")
        ):
            raise BackupValidationError(
                "Backup current QA result lacks its exact Generated Page projection."
            )


def _is_lower_sha256(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _is_nonempty_normalized_string_list(value: object) -> bool:
    return bool(
        isinstance(value, list)
        and value
        and all(
            isinstance(item, str) and item == item.strip().lower() and item
            for item in value
        )
        and len(set(value)) == len(value)
    )


def _is_nonempty_trimmed_string_list(value: object) -> bool:
    """Validate governed prose lists without forcing machine-key casing."""

    return bool(
        isinstance(value, list)
        and value
        and all(
            isinstance(item, str) and item == item.strip() and item
            for item in value
        )
        and len(set(value)) == len(value)
    )


def _is_safe_backup_filename(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and value
        and value == value.strip()
        and value not in {".", ".."}
        and "/" not in value
        and "\\" not in value
        and "\x00" not in value
        and all(ord(character) >= 32 and ord(character) != 127 for character in value)
        and Path(value).name == value
    )


def _is_normalized_string_list(value: list[object]) -> bool:
    return bool(
        value
        and all(isinstance(item, str) and item == item.strip().lower() and item for item in value)
        and len(set(value)) == len(value)
    )


def _is_positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _safe_configured_media_base(value: str) -> str | None:
    base = value.rstrip("/")
    if not base:
        return None
    try:
        parsed = urlsplit(base)
        parsed.port
    except ValueError:
        return None
    if parsed.query or parsed.fragment:
        return None
    if parsed.scheme or parsed.netloc:
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.hostname is None
        ):
            return None
        return base
    if not base.startswith("/") or base.startswith("//"):
        return None
    return base


def _has_coherent_managed_asset_urls(
    record: dict[str, Any],
    stored_filename: str,
    configured_media_public_url: str,
) -> bool:
    public_base = _safe_configured_media_base(configured_media_public_url)
    if public_base is None:
        return False
    stem = Path(stored_filename).stem
    expected_optimized = {
        f"{public_base}/optimized/{stem}-optimized.webp",
        f"{public_base}/optimized/{stem}-optimized.jpg",
    }
    expected_thumbnail = {
        f"{public_base}/thumbnails/{stem}-thumbnail.webp",
        f"{public_base}/thumbnails/{stem}-thumbnail.jpg",
    }
    return bool(
        record.get("asset_url") == f"{public_base}/originals/{stored_filename}"
        and record.get("optimized_url") in expected_optimized
        and record.get("thumbnail_url") in expected_thumbnail
    )


def _has_coherent_page_media_urls(
    record: dict[str, Any],
    stored_filename: str,
    configured_media_public_url: str,
) -> bool:
    public_base = _safe_configured_media_base(configured_media_public_url)
    if public_base is None:
        return False
    stem = Path(stored_filename).stem
    expected_optimized = {
        f"{public_base}/optimized/{stem}-optimized.webp",
        f"{public_base}/optimized/{stem}-optimized.jpg",
    }
    expected_thumbnail = {
        f"{public_base}/thumbnails/{stem}-thumbnail.webp",
        f"{public_base}/thumbnails/{stem}-thumbnail.jpg",
    }
    return bool(
        record.get("optimized_url") in expected_optimized
        and record.get("thumbnail_url") in expected_thumbnail
        and record.get("asset_url") == record.get("optimized_url")
    )


def _restore_target_requires_metadata_bootstrap(bind: Any) -> bool:
    """Reserve all-metadata create_all for a genuinely unmanaged target."""

    return not sa_inspect(bind).has_table("alembic_version")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export or restore Project Atlas JSON backups.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("export", help="Export all Atlas data to the backups folder.")
    restore_parser = subparsers.add_parser("restore", help="Restore a JSON backup with non-destructive upserts.")
    restore_parser.add_argument("backup_file", help="Path or file name of the backup to restore.")
    args = parser.parse_args()

    try:
        restore_path: Path | None = None
        if args.command == "restore":
            # Validate the complete raw contract before the restore-only schema
            # opt-in mutates an otherwise empty target database.
            restore_path = resolve_backup_path(args.backup_file)
            load_backup(restore_path)
        include_alembic_owned = bool(
            args.command == "restore"
            and _restore_target_requires_metadata_bootstrap(engine)
        )
        # A direct restore into a genuinely unmanaged target retains the
        # explicit all-metadata opt-in. Once Alembic owns the target, its
        # revision—not model metadata—must create governed tables; otherwise a
        # 0.57 restore at 0046 would pre-create 0047 tables and make the
        # additive migration correctly refuse the target.
        create_db_and_tables(include_alembic_owned=include_alembic_owned)
        with Session(engine) as session:
            if args.command == "export":
                result = export_backup(session)
            else:
                if restore_path is None:  # pragma: no cover - parser narrows this
                    raise BackupValidationError(
                        "Restore path resolution did not complete."
                    )
                result = restore_backup(session, restore_path)
    except (BackupValidationError, OSError) as exc:
        parser.exit(1, f"Backup error: {exc}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
