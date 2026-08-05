import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit

from sqlmodel import Session, SQLModel, select

from app.core.config import get_settings
from app.db.session import create_db_and_tables, engine
from app.models import (
    ApprovalAudit,
    Brand,
    BrandAsset,
    Business,
    City,
    County,
    DraftingEligibilityAssessment,
    DraftingEligibilityDisposition,
    WebsiteDraftGenerationItem,
    WebsiteDraftGenerationRun,
    GeneratedPage,
    GeneratedPageRevision,
    ImageMetadata,
    InternalLinkIntent,
    KnowledgeBlock,
    NavigationItem,
    NavigationSet,
    PageComposition,
    PageImageAssignment,
    PlannedPage,
    PlanningRecord,
    PreDraftDistinctnessBrief,
    SiteConnectionPlanningRecord,
    Service,
    SemanticComponentDefinition,
    Setting,
    SitePlan,
    SupportingPageAuthorization,
    Theme,
    Website,
    WebsiteCityCoverageDecision,
    WebsiteCountyCoverageDecision,
    WebsiteCoveragePlanningRecord,
    WebsiteIdentity,
    WebsiteIdentityAssetAssignment,
    WebsiteThemeSelection,
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

APP_NAME = "Project Atlas"
BACKUP_VERSION = "0.52"
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
    "site_plans": SitePlan,
    "planned_pages": PlannedPage,
    "planning_records": PlanningRecord,
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
        for record in data["generated_pages"]:
            old_id = _record_id(record, "generated_pages")
            restored_record = {
                **record,
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
            generated_page_ids[old_id] = _required_id(restored)

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

        for record in data.get("internal_link_intents", []):
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
            _upsert(
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

        for record in data.get("page_compositions", []):
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
            _upsert(
                session,
                PageComposition,
                select(PageComposition).where(
                    PageComposition.planned_page_id == planned_page_id
                ),
                {
                    **record,
                    "source_snapshot": restored_snapshot,
                    "source_hash": _canonical_json_hash(restored_snapshot),
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
        if payload["metadata"]["version"] not in {
            "0.44",
            "0.45",
            "0.46",
            "0.47",
            "0.48",
            "0.49",
        }:
            from app.services.site_connections import (
                ensure_site_connection_foundation,
            )

            for restored_plan_id in site_plan_ids.values():
                restored_plan = session.get(SitePlan, restored_plan_id)
                if restored_plan:
                    ensure_site_connection_foundation(
                        session,
                        restored_plan,
                        commit=False,
                    )
        if payload["metadata"]["version"] not in {
            "0.45",
            "0.46",
            "0.47",
            "0.48",
            "0.49",
        }:
            from app.services.site_coverage import ensure_coverage_foundation

            for restored_plan_id in site_plan_ids.values():
                restored_plan = session.get(SitePlan, restored_plan_id)
                if restored_plan:
                    ensure_coverage_foundation(
                        session,
                        restored_plan,
                        commit=False,
                    )

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

        if data.get("page_compositions"):
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
                    payload["metadata"]["version"] == "0.52"
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
                    observed_count = (
                        result.created + result.refreshed + result.unchanged
                    )
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
    if backup_version not in {"0.43", "0.44", "0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52"}:
        for group in ("site_plans", "planned_pages", "planning_records"):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.44", "0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52"}:
        for group in (
            "site_connection_planning_records",
            "navigation_sets",
            "navigation_items",
            "internal_link_intents",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.45", "0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52"}:
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
    if backup_version not in {"0.46", "0.47", "0.48", "0.49", "0.50", "0.51", "0.52"}:
        for group in (
            "drafting_eligibility_assessments",
            "drafting_eligibility_dispositions",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.47", "0.48", "0.49", "0.50", "0.51", "0.52"}:
        for group in (
            "supporting_page_authorizations",
            "pre_draft_distinctness_briefs",
        ):
            if group not in data:
                data[group] = []
                counts[group] = 0
    if backup_version not in {"0.48", "0.49", "0.50", "0.51", "0.52"}:
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
    if backup_version not in {"0.49", "0.50", "0.51", "0.52"}:
        for group in ("semantic_component_definitions", "page_compositions"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.50", "0.51", "0.52"}:
        for group in ("brand_assets", "website_identity_asset_assignments"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)
    if backup_version not in {"0.51", "0.52"}:
        for group in ("themes", "website_theme_selections"):
            data.setdefault(group, [])
            counts.setdefault(group, 0)

    for group in BACKUP_MODELS:
        records = data.get(group)
        if not isinstance(records, list):
            raise BackupValidationError(f"Backup data group '{group}' must be a list.")
        if counts.get(group) != len(records):
            raise BackupValidationError(f"Backup count mismatch for '{group}'.")
        if not all(isinstance(record, dict) for record in records):
            raise BackupValidationError(f"Backup data group '{group}' contains an invalid record.")

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
    _validate_unique_records(data)
    _validate_backup_references(data)
    _validate_brand_asset_ownership(data)
    _validate_theme_ownership(data)
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


def _canonical_json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


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


def _comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _validate_site_connection_decision_provenance(
    data: dict[str, list[dict[str, Any]]],
    backup_version: str,
) -> None:
    if backup_version == "0.52":
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

    if backup_version != "0.52":
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
