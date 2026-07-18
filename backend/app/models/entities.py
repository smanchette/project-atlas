from datetime import UTC, datetime
from typing import Any

from sqlalchemy import CheckConstraint, Column, JSON, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(UTC)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utc_now, nullable=False)
    updated_at: datetime = Field(default_factory=utc_now, nullable=False)


class Business(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    company_name: str = Field(index=True)
    brand_name: str | None = Field(default=None, index=True)
    business_type: str
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    main_city: str | None = Field(default=None, index=True)
    state: str = Field(default="FL", max_length=2, index=True)
    license_number: str | None = None
    certified_operator: str | None = None
    description: str | None = None


class Service(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_name: str = Field(index=True)
    service_slug: str = Field(index=True, unique=True)
    service_category: str | None = Field(default=None, index=True)
    short_description: str | None = None
    long_description: str | None = None
    status: str = Field(default="active", index=True)


class County(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    state: str = Field(default="FL", max_length=2, index=True)
    county_name: str = Field(index=True)
    status: str = Field(default="active", index=True)


class City(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    county_id: int = Field(foreign_key="county.id", index=True)
    city_name: str = Field(index=True)
    state: str = Field(default="FL", max_length=2, index=True)
    city_slug: str = Field(index=True, unique=True)
    priority: str = Field(default="Medium", index=True)
    is_primary_market: bool = Field(default=False, index=True)
    notes: str | None = None
    status: str = Field(default="active", index=True)


class GeneratedPage(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="city.id", index=True)
    county_id: int | None = Field(default=None, foreign_key="county.id", index=True)
    page_type: str = Field(index=True)
    page_title: str
    page_slug: str = Field(index=True, unique=True)
    meta_title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    content_body: str | None = None
    draft_content: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    generation_status: str = Field(default="not_generated", index=True)
    generated_at: datetime | None = None
    qa_status: str = Field(default="not_run", index=True)
    qa_result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    qa_checked_at: datetime | None = None
    internal_notes: str | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_by: str | None = None
    status: str = Field(default="draft", index=True)
    wordpress_post_id: int | None = Field(default=None, index=True)
    wordpress_url: str | None = None
    wordpress_status: str | None = Field(default=None, index=True)
    wordpress_created_at: datetime | None = None
    last_wordpress_sync_at: datetime | None = None


class ApprovalAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "approved_at",
            "draft_hash_at_approval",
            name="uq_approvalaudit_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    approved_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    approved_by: str | None = None
    qa_status_at_approval: str = Field(index=True)
    qa_checked_at: datetime
    qa_result_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    draft_hash_at_approval: str = Field(index=True)
    page_status_before: str
    page_status_after: str


class GeneratedPageRevision(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "created_at",
            "draft_hash_after",
            name="uq_pagerevision_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    created_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    created_by: str | None = None
    reason: str | None = None
    draft_hash_before: str
    draft_hash_after: str = Field(index=True)
    draft_content_before: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    draft_content_after: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    changed_fields: list[str] = Field(sa_column=Column(JSON, nullable=False))


class WordPressDraftAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "attempted_at",
            "payload_hash",
            name="uq_wordpressdraftaudit_page_time_hash",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    action_type: str = Field(default="create_draft", index=True)
    status: str = Field(index=True)
    wordpress_site_url: str
    wordpress_post_id: int | None = Field(default=None, index=True)
    wordpress_status: str | None = Field(default=None, index=True)
    slug: str = Field(index=True)
    payload_hash: str = Field(index=True)
    qa_status_at_attempt: str
    qa_checked_at: datetime | None = None
    draft_hash_at_attempt: str = Field(index=True)
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    error_message: str | None = None


class WordPressPublishAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id", "attempted_at", "publish_payload_hash",
            name="uq_wordpresspublishaudit_page_time_hash",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    wordpress_site_url: str
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    status: str = Field(default="pending", index=True)
    pre_publish_wordpress_status: str | None = None
    returned_wordpress_status: str | None = None
    returned_wordpress_url: str | None = None
    current_draft_payload_hash: str = Field(index=True)
    latest_update_audit_id: int | None = Field(default=None, foreign_key="wordpressdraftaudit.id")
    latest_update_audit_hash: str
    publish_payload_hash: str = Field(index=True)
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    backup_file_name: str
    error_message: str | None = None


class WordPressQualityReview(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            name="uq_wordpressqualityreview_generated_page_id",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    review_status: str = Field(default="not_reviewed", index=True)
    reviewer_notes: str | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None


class ImageMetadata(TimestampMixin, table=True):
    __table_args__ = (
        CheckConstraint("focal_x >= 0 AND focal_x <= 1", name="ck_imagemetadata_focal_x_range"),
        CheckConstraint("focal_y >= 0 AND focal_y <= 1", name="ck_imagemetadata_focal_y_range"),
    )

    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_id: int | None = Field(default=None, foreign_key="service.id", index=True)
    city_id: int | None = Field(default=None, foreign_key="city.id", index=True)
    county_id: int | None = Field(default=None, foreign_key="county.id", index=True)
    file_name: str = Field(index=True)
    image_title: str | None = None
    alt_text: str | None = None
    reviewed_alt_text: str | None = None
    caption: str | None = None
    asset_url: str | None = None
    thumbnail_url: str | None = None
    optimized_url: str | None = None
    original_filename: str | None = None
    stored_filename: str | None = None
    notes: str | None = None
    focal_x: float = Field(default=0.5, ge=0, le=1)
    focal_y: float = Field(default=0.5, ge=0, le=1)
    image_role: str = Field(default="support", index=True)
    review_status: str = Field(default="pending", index=True)
    geo_city: str | None = Field(default=None, index=True)
    geo_state: str | None = Field(default="FL", max_length=2, index=True)
    image_prompt: str | None = None
    exif_status: str = Field(default="pending", index=True)
    wordpress_media_id: int | None = Field(default=None, index=True)
    wordpress_media_url: str | None = None
    wordpress_media_status: str | None = Field(default=None, index=True)
    wordpress_media_checksum: str | None = Field(default=None, index=True)
    wordpress_media_uploaded_at: datetime | None = None
    last_wordpress_media_sync_at: datetime | None = None


class WordPressMediaSyncAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("generated_page_id", "attempted_at", "source_checksum", name="uq_wordpressmediasyncaudit_page_time_checksum"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    image_metadata_id: int = Field(foreign_key="imagemetadata.id", index=True)
    page_image_assignment_id: int = Field(foreign_key="pageimageassignment.id", index=True)
    wordpress_post_id: int = Field(index=True)
    wordpress_media_id: int | None = Field(default=None, index=True)
    action_type: str = Field(default="upload_media", index=True)
    status: str = Field(default="pending", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    wordpress_site_url: str
    source_file_name: str
    source_mime_type: str
    source_file_size: int
    source_width: int
    source_height: int
    source_checksum: str = Field(index=True)
    alt_text: str
    returned_media_url: str | None = None
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    backup_file_name: str
    error_message: str | None = None


class WordPressMetadataState(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint("generated_page_id", name="uq_wordpressmetadatastate_generated_page_id"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    schema_version: str = Field(default="1.0")
    status: str = Field(default="not_applied", index=True)
    payload: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    payload_hash: str | None = Field(default=None, index=True)
    wordpress_revision: str | None = None
    last_verified_at: datetime | None = None
    last_wordpress_metadata_sync_at: datetime | None = None


class WordPressMetadataSyncAudit(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id", "attempted_at", "payload_hash",
            name="uq_wordpressmetadatasyncaudit_page_time_hash",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(index=True)
    status: str = Field(default="pending", index=True)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    wordpress_site_url: str
    payload_hash: str = Field(index=True)
    payload_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    previous_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    returned_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    data_backup_file_name: str
    wordpress_backup_reference: str
    plugin_version: str
    error_message: str | None = None


class WordPressDeploymentAudit(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint("action_type = 'install_metadata_bridge'", name="ck_wordpressdeploymentaudit_action"),
        CheckConstraint(
            "status IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymentaudit_status",
        ),
        UniqueConstraint("deployment_key", name="uq_wordpressdeploymentaudit_deployment_key"),
        UniqueConstraint("authorization_jti", name="uq_wordpressdeploymentaudit_authorization_jti"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(max_length=64, index=True)
    status: str = Field(max_length=40, index=True)
    operator: str = Field(max_length=200)
    shawn_approved_at: datetime
    confirmation_phrase_hash: str = Field(max_length=64)
    atlas_version: str = Field(max_length=32)
    atlas_commit: str = Field(max_length=40)
    atlas_tag: str = Field(max_length=32)
    plugin_version: str = Field(max_length=32)
    plugin_slug: str = Field(max_length=100)
    plugin_path: str = Field(max_length=255)
    zip_file_name: str = Field(max_length=255)
    zip_sha256: str = Field(max_length=64)
    plugin_source_sha256: str = Field(max_length=64)
    installation_transport: str = Field(default="manual_wordpress_admin_upload", max_length=64)
    backup_reference: str = Field(max_length=255, index=True)
    backup_completed_at: datetime
    backup_deadline: datetime = Field(index=True)
    authorization_jti: str = Field(max_length=64, index=True)
    deployment_key: str = Field(max_length=64, index=True)
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    evidence_summary: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    evidence_directory: str = Field(max_length=500)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    partial_failure_details: str | None = None


class WordPressHeadingCorrectionAudit(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "action_type = 'correct_orlando_duplicate_h1'",
            name="ck_wordpressheadingcorrectionaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','corrected','verified','reconciliation_required','failed')",
            name="ck_wordpressheadingcorrectionaudit_status",
        ),
        UniqueConstraint(
            "token_fingerprint",
            name="uq_wordpressheadingcorrectionaudit_token_fingerprint",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    action_type: str = Field(default="correct_orlando_duplicate_h1", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    wordpress_site_url: str = Field(max_length=500)
    current_body_hash: str = Field(max_length=64, index=True)
    proposed_body_hash: str = Field(max_length=64, index=True)
    token_fingerprint: str = Field(max_length=64, index=True)
    backup_identities: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressDeploymentNonce(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("jti", name="uq_wordpressdeploymentnonce_jti"),
        UniqueConstraint("token_fingerprint", name="uq_wordpressdeploymentnonce_token_fingerprint"),
    )
    id: int | None = Field(default=None, primary_key=True)
    jti: str = Field(max_length=64, index=True)
    token_fingerprint: str = Field(max_length=64)
    action_type: str = Field(max_length=64, index=True)
    consumed_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    audit_id: int | None = Field(default=None, foreign_key="wordpressdeploymentaudit.id", index=True)


class WordPressDeploymentTransition(SQLModel, table=True):
    __table_args__ = (
        CheckConstraint(
            "previous_state IS NULL OR previous_state IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymenttransition_previous_state",
        ),
        CheckConstraint(
            "new_state IN ('installation_authorized','awaiting_manual_installation','manual_installation_reported','verification_pending','verified','verification_failed','reconciliation_required','failed')",
            name="ck_wordpressdeploymenttransition_new_state",
        ),
        UniqueConstraint("request_identifier", name="uq_wordpressdeploymenttransition_request_identifier"),
    )
    id: int | None = Field(default=None, primary_key=True)
    audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    previous_state: str | None = Field(default=None, max_length=40)
    new_state: str = Field(max_length=40, index=True)
    transitioned_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    actor: str = Field(max_length=200)
    reason: str = Field(max_length=500)
    request_identifier: str = Field(max_length=64, index=True)


class WordPressActivationAudit(SQLModel, table=True):
    """Durable record for the separately authorized Metadata Bridge activation."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'activate_metadata_bridge'",
            name="ck_wordpressactivationaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpressactivationaudit_status",
        ),
        UniqueConstraint(
            "handle_fingerprint",
            name="uq_wordpressactivationaudit_handle_fingerprint",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    action_type: str = Field(default="activate_metadata_bridge", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    atlas_version: str = Field(max_length=32)
    atlas_commit: str = Field(max_length=40)
    atlas_tag: str = Field(max_length=32)
    manifest_sha256: str = Field(max_length=64)
    plugin_slug: str = Field(max_length=100)
    plugin_path: str = Field(max_length=255)
    plugin_version: str = Field(max_length=32)
    zip_sha256: str = Field(max_length=64)
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=100)
    browser_evidence_schema: str = Field(max_length=100)
    browser_evidence_schema_version: int
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressPluginUpgradeAudit(SQLModel, table=True):
    """Durable record for one guarded Metadata Bridge artifact replacement."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'upgrade_metadata_bridge'",
            name="ck_wordpresspluginupgradeaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpresspluginupgradeaudit_status",
        ),
        UniqueConstraint(
            "handle_fingerprint",
            name="uq_wordpresspluginupgradeaudit_handle_fingerprint",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    action_type: str = Field(default="upgrade_metadata_bridge", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    previous_version: str = Field(max_length=32)
    target_version: str = Field(max_length=32)
    previous_artifact_sha256: str = Field(max_length=64)
    target_artifact_sha256: str = Field(max_length=64)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    previous_inventories: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    final_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    metadata_rendering_state: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    verification_findings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressBootstrapCleanupAudit(SQLModel, table=True):
    """Durable record for the separately gated upgrade-bootstrap cleanup."""

    __table_args__ = (
        CheckConstraint(
            "action_type = 'cleanup_upgrade_bootstrap'",
            name="ck_wordpressbootstrapcleanupaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','deactivated','verified','verification_failed','failed')",
            name="ck_wordpressbootstrapcleanupaudit_status",
        ),
        UniqueConstraint(
            "deactivation_handle_fingerprint",
            name="uq_wordpressbootstrapcleanupaudit_deactivation_handle",
        ),
        UniqueConstraint(
            "deletion_handle_fingerprint",
            name="uq_wordpressbootstrapcleanupaudit_deletion_handle",
        ),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    upgrade_audit_id: int = Field(foreign_key="wordpresspluginupgradeaudit.id", index=True)
    action_type: str = Field(default="cleanup_upgrade_bootstrap", max_length=64, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    bootstrap_slug: str = Field(max_length=100)
    bootstrap_path: str = Field(max_length=255)
    bootstrap_version: str = Field(max_length=32)
    bootstrap_zip_sha256: str = Field(max_length=64)
    bridge_version: str = Field(max_length=32)
    deactivation_phrase_hash: str = Field(max_length=64)
    deletion_phrase_hash: str = Field(max_length=64)
    deactivation_handle_fingerprint: str = Field(max_length=64, index=True)
    deletion_handle_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    deactivation_binding_hash: str = Field(max_length=64, index=True)
    deletion_binding_hash: str | None = Field(default=None, max_length=64, index=True)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    deactivated_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    previous_inventories: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    deactivated_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    final_inventories: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    metadata_rendering_state: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    verification_findings: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    deactivated_at: datetime | None = None
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)


class WordPressMetadataLifecycleAudit(SQLModel, table=True):
    """Durable record for one isolated Metadata Bridge lifecycle mutation."""

    __table_args__ = (
        CheckConstraint(
            "action_type IN ('stage_metadata_payload','enable_metadata_rendering','disable_metadata_rendering','rollback_metadata_payload')",
            name="ck_wordpressmetadatalifecycleaudit_action",
        ),
        CheckConstraint(
            "status IN ('pending','verified','verification_failed','failed')",
            name="ck_wordpressmetadatalifecycleaudit_status",
        ),
        UniqueConstraint("handle_fingerprint", name="uq_wordpressmetadatalifecycleaudit_handle_fingerprint"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    installation_audit_id: int = Field(foreign_key="wordpressdeploymentaudit.id", index=True)
    activation_audit_id: int = Field(foreign_key="wordpressactivationaudit.id", index=True)
    action_type: str = Field(max_length=64, index=True)
    completion_mode: str = Field(default="standard", max_length=80, index=True)
    status: str = Field(default="pending", max_length=40, index=True)
    operator: str = Field(max_length=200)
    confirmation_phrase_hash: str = Field(max_length=64)
    handle_fingerprint: str = Field(max_length=64, index=True)
    binding_hash: str = Field(max_length=64, index=True)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    browser_evidence_id: str = Field(max_length=200)
    browser_evidence_hashes: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    payload_hash: str = Field(default="", max_length=64, index=True)
    previous_revision: str = Field(max_length=40)
    final_revision: str | None = Field(default=None, max_length=40)
    previous_rendering_enabled: bool
    final_rendering_enabled: bool | None = None
    pre_snapshot: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    post_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_count: int = Field(default=0)
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, max_length=2000)
    recovery_recommendation: str | None = Field(default=None, max_length=64)


class WordPressCacheAwareRenderingAudit(SQLModel, table=True):
    """Durable orchestration record for rendering, origin proof, and one URL purge."""

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending_rendering','origin_verified','pending_cache_purge','verified','verification_failed','failed')",
            name="ck_wordpresscacheawarerenderingaudit_status",
        ),
        UniqueConstraint("rendering_handle_fingerprint", name="uq_cacheaware_rendering_handle"),
        UniqueConstraint("cache_handle_fingerprint", name="uq_cacheaware_cache_handle"),
    )
    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    wordpress_post_id: int = Field(index=True)
    staging_audit_id: int = Field(foreign_key="wordpressmetadatalifecycleaudit.id", index=True)
    recovery_disable_audit_id: int = Field(foreign_key="wordpressmetadatalifecycleaudit.id", index=True)
    status: str = Field(default="pending_rendering", max_length=40, index=True)
    operator: str = Field(max_length=200)
    rendering_handle_fingerprint: str = Field(max_length=64, index=True)
    cache_handle_fingerprint: str | None = Field(default=None, max_length=64, index=True)
    rendering_binding_hash: str = Field(max_length=64, index=True)
    cache_binding_hash: str | None = Field(default=None, max_length=64, index=True)
    rendering_phrase_hash: str = Field(max_length=64)
    cache_phrase_hash: str | None = Field(default=None, max_length=64)
    release_identity: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    backup_evidence: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    payload_hash: str = Field(max_length=64, index=True)
    revision: str = Field(max_length=40)
    cache_provider: str | None = Field(default=None, max_length=80)
    cache_scope: str | None = Field(default=None, max_length=80)
    cache_target: str | None = Field(default=None, max_length=500)
    pre_purge_headers: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    post_purge_headers: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    origin_verification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    public_verification: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    public_evidence: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    page_media_snapshots: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    gate_results: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    wordpress_write_count: int = Field(default=0)
    cache_write_count: int = Field(default=0)
    atlas_write_count: int = Field(default=0)
    wordpress_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    cache_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    atlas_write_scope: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    transition_history: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    final_state: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    recovery_recommendation: str | None = Field(default=None, max_length=64)
    attempted_at: datetime = Field(default_factory=utc_now, nullable=False, index=True)
    completed_at: datetime | None = None
    error_code: str | None = Field(default=None, max_length=80)
    error_message: str | None = Field(default=None, max_length=2000)


class PageImageAssignment(TimestampMixin, table=True):
    __table_args__ = (
        UniqueConstraint(
            "generated_page_id",
            "image_metadata_id",
            "image_role",
            name="uq_page_image_role_media",
        ),
        CheckConstraint(
            "override_focal_x IS NULL OR (override_focal_x >= 0 AND override_focal_x <= 1)",
            name="ck_pageimageassignment_override_focal_x_range",
        ),
        CheckConstraint(
            "override_focal_y IS NULL OR (override_focal_y >= 0 AND override_focal_y <= 1)",
            name="ck_pageimageassignment_override_focal_y_range",
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    generated_page_id: int = Field(foreign_key="generatedpage.id", index=True)
    image_metadata_id: int = Field(foreign_key="imagemetadata.id", index=True)
    image_role: str = Field(default="hero", index=True)
    sort_order: int = Field(default=0)
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str = Field(default="hero_desktop", index=True)
    status: str = Field(default="active", index=True)


class KnowledgeBlock(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    business_id: int = Field(foreign_key="business.id", index=True)
    service_id: int = Field(foreign_key="service.id", index=True)
    title: str = Field(index=True)
    slug: str = Field(index=True, unique=True)
    question: str
    short_answer: str
    long_answer: str
    category: str = Field(index=True)
    customer_type: str = Field(default="general", index=True)
    confidence_level: str = Field(default="Medium", index=True)
    source_notes: str | None = None
    sort_order: int = Field(default=0, index=True)
    status: str = Field(default="active", index=True)


class Setting(TimestampMixin, table=True):
    id: int | None = Field(default=None, primary_key=True)
    setting_key: str = Field(index=True, unique=True)
    setting_value: str | None = None
    description: str | None = None
