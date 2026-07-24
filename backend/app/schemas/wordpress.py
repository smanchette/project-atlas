from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Literal

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

PublishingMode = Literal["disabled", "sandbox", "draft_only_future"]


class WordPressSettingsRead(SQLModel):
    site_url: str = ""
    username: str = ""
    publishing_mode: PublishingMode = "disabled"
    has_application_password: bool = False
    password_storage: str = "Process memory only. It is cleared when the backend restarts."


class WordPressSettingsUpdate(SQLModel):
    site_url: str = ""
    username: str = ""
    application_password: str | None = Field(default=None, max_length=512)
    publishing_mode: PublishingMode = "disabled"
    clear_application_password: bool = False

    @field_validator("site_url", "username", "application_password", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class WordPressConnectionResult(SQLModel):
    connection_status: Literal["disabled", "connected", "failed"]
    rest_api_reachable: bool
    authenticated: bool
    credentials_present: bool = False
    site_name: str | None = None
    error_message: str | None = None
    endpoint: str | None = None
    response_source: str | None = None
    reason_code: str | None = None
    authenticated_user_id: int | None = None
    authenticated_username: str | None = None
    atlas_status_checked: bool = False
    atlas_status_reachable: bool = False
    atlas_status_code: int | None = None


class WordPressPayload(SQLModel):
    title: str
    slug: str
    status: Literal["draft"] = "draft"
    content: str
    excerpt: str
    featured_media_reference: dict[str, Any] | None = None
    meta: dict[str, str]
    schema_block_preview: dict[str, Any]


class WordPressHeadingContract(SQLModel):
    policy_id: str = Field(min_length=3, max_length=100)
    template_renders_primary_h1: bool
    body_heading_level: Literal[1, 2]

    @model_validator(mode="after")
    def validate_heading_ownership(self) -> "WordPressHeadingContract":
        expected_level = 2 if self.template_renders_primary_h1 else 1
        if self.body_heading_level != expected_level:
            raise ValueError(
                "The body heading must be H2 when the template owns the primary H1, "
                "and H1 otherwise."
            )
        return self


class WordPressPayloadPreview(SQLModel):
    page_id: int
    export_package: dict[str, Any]
    payload: WordPressPayload
    heading_contract: WordPressHeadingContract
    warnings: list[dict[str, str]]
    sandbox_only: bool = True


class WordPressHeadingCorrectionDryRun(SQLModel):
    atlas_page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["blocked", "dry_run_ready"]
    ready: bool
    heading_contract: WordPressHeadingContract
    current_body_hash: str | None = None
    proposed_body_hash: str | None = None
    current_heading_fragment: str
    proposed_heading_fragment: str
    request_payload: dict[str, str]
    gate_results: list["WordPressDraftGateResult"]
    read_only: Literal[True] = True
    token_issued: bool = False
    nonce_consumed: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0
    backup_identities: "WordPressHeadingCorrectionBackupIdentities | None" = None
    release_identity: dict[str, Any] | None = None
    pre_snapshot: dict[str, Any] | None = None
    page_8_observation: "WordPressHeadingCorrectionObservationResult | None" = None
    media_31_observation: "WordPressHeadingCorrectionObservationResult | None" = None
    media_32_observation: "WordPressHeadingCorrectionObservationResult | None" = None
    rendered_page_observation: "WordPressHeadingCorrectionObservationResult | None" = None
    token_handle: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None


class WordPressHeadingCorrectionBackupIdentities(SQLModel):
    model_config = ConfigDict(extra="forbid")

    data_backup_file_name: str = Field(
        min_length=10,
        max_length=255,
    )
    media_backup_file_name: str = Field(
        min_length=10,
        max_length=255,
    )
    program_backup_file_name: str = Field(
        min_length=10,
        max_length=255,
    )

    @field_validator(
        "data_backup_file_name",
        "media_backup_file_name",
        "program_backup_file_name",
    )
    @classmethod
    def validate_backup_name(cls, value: str, info: Any) -> str:
        patterns = {
            "data_backup_file_name": r"^atlas-backup-\d{4}-\d{2}-\d{2}-\d{6}\.json$",
            "media_backup_file_name": r"^atlas-media-backup-\d{4}-\d{2}-\d{2}-\d{6}\.zip$",
            "program_backup_file_name": r"^atlas-program-backup-\d{4}-\d{2}-\d{2}-\d{6}\.zip$",
        }
        import re

        if re.fullmatch(patterns[info.field_name], value) is None:
            raise ValueError("Atlas backup identity has an invalid filename.")
        return value


class WordPressHeadingCorrectionObservationResult(SQLModel):
    model_config = ConfigDict(extra="forbid")

    attempted: bool
    acquisition_source: str = Field(min_length=1, max_length=100)
    http_status: int | None = None
    final_url: str | None = None
    success: bool
    failure_code: str | None = None
    message: str = Field(min_length=1, max_length=500)


class WordPressHeadingCorrectionDryRunRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    backups: WordPressHeadingCorrectionBackupIdentities
    manual_browser_evidence: "WordPressManualBrowserEvidence | None" = None


class WordPressHeadingContentPayload(SQLModel):
    model_config = ConfigDict(extra="forbid")

    content: str


class WordPressHeadingCorrectionApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    backups: WordPressHeadingCorrectionBackupIdentities
    token_handle: str = Field(default="", max_length=200)
    confirmation_phrase: str = Field(default="", max_length=100)


class WordPressHeadingCorrectionApplyResult(SQLModel):
    atlas_page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["corrected", "reconciliation_required"]
    audit_id: int
    current_body_hash: str
    proposed_body_hash: str
    request_payload: WordPressHeadingContentPayload
    gate_results: list["WordPressDraftGateResult"]
    wordpress_write_count: Literal[1] = 1
    atlas_write_count: int = 2
    automatic_retry_count: Literal[0] = 0


class WordPressHeadingCorrectionVerifyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: int | None = Field(default=None, ge=1)
    manual_browser_evidence: "WordPressManualBrowserEvidence | None" = None


class WordPressHeadingCorrectionVerification(SQLModel):
    atlas_page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["verified", "blocked", "reconciliation_ready"]
    verified: bool
    audit_id: int | None = None
    body_hash: str | None = None
    rendered_h1_count: int | None = None
    rendered_h1_text: str | None = None
    gate_results: list["WordPressDraftGateResult"]
    snapshot: dict[str, Any] | None = None
    page_8_observation: WordPressHeadingCorrectionObservationResult
    media_31_observation: WordPressHeadingCorrectionObservationResult
    media_32_observation: WordPressHeadingCorrectionObservationResult
    rendered_page_observation: WordPressHeadingCorrectionObservationResult
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0
    cache_purge_count: Literal[0] = 0


class WordPressHeadingCorrectionReconcileRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: int = Field(ge=1)
    confirmation_phrase: str = Field(min_length=1, max_length=100)
    manual_browser_evidence: "WordPressManualBrowserEvidence | None" = None


class WordPressHeadingCorrectionReconcileResult(SQLModel):
    atlas_page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["verified"] = "verified"
    audit_id: int
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[1] = 1
    gate_results: list["WordPressDraftGateResult"]


class WordPressDraftGateResult(SQLModel):
    code: str
    label: str
    passed: bool
    message: str


class WordPressDraftRequestPayload(SQLModel):
    title: str
    slug: str
    status: Literal["draft"] = "draft"
    content: str
    excerpt: str


class WordPressDraftDryRun(SQLModel):
    page_id: int
    status: Literal["blocked", "dry_run_ready"]
    ready: bool
    payload: WordPressDraftRequestPayload
    payload_hash: str
    draft_hash: str
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None


class WordPressDraftUpdateComparison(SQLModel):
    original_create_audit_id: int | None = None
    original_payload_hash: str | None = None
    current_payload_hash: str
    original_draft_hash: str | None = None
    current_draft_hash: str
    payload_changed_since_create: bool = False
    media_reference_hash: str
    media_reference_warning: str | None = None
    changed_summary: list[str] = []


class WordPressDraftUpdateDryRun(SQLModel):
    page_id: int
    status: Literal["blocked", "dry_run_ready"]
    ready: bool
    wordpress_post_id: int | None = None
    live_status: WordPressLiveDraftStatus | None = None
    payload: WordPressDraftRequestPayload
    comparison: WordPressDraftUpdateComparison
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    dry_run_only: bool = True


class WordPressDraftUpdateApplyRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=300)


class WordPressDraftUpdateApplyResult(SQLModel):
    page_id: int
    status: Literal["updated"]
    wordpress_post_id: int
    wordpress_status: Literal["draft"]
    wordpress_url: str | None = None
    audit_id: int
    payload_hash: str
    gate_results: list[WordPressDraftGateResult]


class WordPressPublishRequestPayload(SQLModel):
    title: str
    slug: str
    status: Literal["publish"] = "publish"
    content: str
    excerpt: str


class WordPressPublishDryRun(SQLModel):
    page_id: int
    status: Literal["blocked", "dry_run_ready"]
    ready: bool
    wordpress_post_id: int | None = None
    live_status: WordPressLiveDraftStatus | None = None
    payload: WordPressPublishRequestPayload
    current_payload_hash: str
    latest_update_audit_hash: str | None = None
    publish_payload_hash: str
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    public_publish_warning: str = "Publishing makes the WordPress page public. Only the guarded one-page apply flow can publish."
    dry_run_only: bool = True


class WordPressPublishApplyRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=300)
    confirmed_backup_file: str = Field(min_length=1, max_length=255)


class WordPressPublishApplyResult(SQLModel):
    page_id: int
    status: Literal["published"]
    wordpress_post_id: int
    wordpress_status: Literal["publish"]
    wordpress_url: str
    audit_id: int
    publish_payload_hash: str
    gate_results: list[WordPressDraftGateResult]


class WordPressMediaAttachmentMatch(SQLModel):
    status: Literal["missing", "matched", "blocked", "unavailable"]
    wordpress_media_id: int | None = None
    wordpress_media_url: str | None = None
    message: str


class WordPressMediaDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    assignment_id: int
    image_id: int
    status: Literal["blocked", "dry_run_ready"]
    ready: bool
    resolved_local_path: str
    source_file_name: str
    original_filename: str | None = None
    mime_type: str
    file_size: int
    width: int
    height: int
    checksum: str
    alt_text: str
    image_title: str
    existing_wordpress_media_id: int | None = None
    existing_wordpress_media_url: str | None = None
    attachment_match: WordPressMediaAttachmentMatch
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    dry_run_only: bool = True


class WordPressMediaUploadRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)
    confirmed_backup_file: str = Field(min_length=1, max_length=255)


class WordPressMediaUploadResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    image_id: int
    assignment_id: int
    status: Literal["uploaded"]
    wordpress_media_id: int
    wordpress_media_url: str
    checksum: str
    alt_text: str
    audit_id: int
    gate_results: list[WordPressDraftGateResult]


class WordPressMediaInspectionCandidate(SQLModel):
    wordpress_media_id: int
    date_gmt: str | None = None
    modified_gmt: str | None = None
    source_url: str | None = None
    mime_type: str | None = None
    slug: str | None = None
    title: str | None = None
    alt_text: str | None = None
    media_file: str | None = None
    atlas_meta: dict[str, Any] = {}
    likely_target: bool
    verification_mismatches: list[str] = []


class WordPressMediaInspectionResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    image_id: int
    source_file_name: str
    expected_title: str
    expected_alt_text: str
    expected_mime_type: str
    expected_checksum: str
    candidate_count: int
    possible_duplicate_count: int
    candidates: list[WordPressMediaInspectionCandidate]
    read_only: bool = True


class WordPressMediaFeaturedReference(SQLModel):
    object_type: Literal["page", "post"]
    object_id: int
    title: str | None = None
    status: str | None = None
    slug: str | None = None
    link: str | None = None


class WordPressMediaReconciliationCandidate(SQLModel):
    wordpress_media_id: int
    date_gmt: str | None = None
    source_url: str | None = None
    title: str | None = None
    alt_text: str | None = None
    mime_type: str | None = None
    width: int | None = None
    height: int | None = None
    file_size: int | None = None
    parent_post_id: int | None = None
    remote_checksum: str | None = None
    featured_references: list[WordPressMediaFeaturedReference] = []
    valid: bool
    gate_results: list[WordPressDraftGateResult]


class WordPressMediaReconciliationDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    image_id: int
    assignment_id: int
    candidate_ids: list[int]
    local_checksum: str
    local_file_size: int
    candidates: list[WordPressMediaReconciliationCandidate]
    selected_media_id: int | None = None
    selected_media_url: str | None = None
    duplicate_candidate_ids: list[int] = []
    post_status: str | None = None
    post_featured_media: int | None = None
    gate_results: list[WordPressDraftGateResult]
    status: Literal["blocked", "reconciliation_ready"]
    ready: bool
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    dry_run_only: bool = True


class WordPressMediaReconciliationApplyRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)
    confirmed_backup_file: str = Field(min_length=1, max_length=255)


class WordPressMediaReconciliationApplyResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    image_id: int
    assignment_id: int
    status: Literal["reconciled"]
    wordpress_media_id: int
    wordpress_media_url: str
    checksum: str
    duplicate_candidate_ids: list[int]
    audit_id: int
    gate_results: list[WordPressDraftGateResult]


class WordPressFeaturedImageDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    image_id: int
    assignment_id: int
    wordpress_media_id: int
    post_status: str | None = None
    post_slug: str | None = None
    post_url: str | None = None
    current_featured_media: int | None = None
    media: WordPressMediaReconciliationCandidate | None = None
    local_checksum: str
    planned_payload: dict[str, int]
    excluded_media_ids: list[int] = []
    gate_results: list[WordPressDraftGateResult]
    status: Literal["blocked", "featured_image_ready"]
    ready: bool
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    dry_run_only: bool = True


class WordPressFeaturedImageApplyRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)
    confirmed_data_backup_file: str = Field(min_length=1, max_length=255)
    confirmed_media_backup_file: str = Field(min_length=1, max_length=255)
    confirmed_program_backup_file: str = Field(min_length=1, max_length=255)


class WordPressFeaturedImageApplyResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    wordpress_media_id: int
    status: Literal["featured_image_set"]
    wordpress_status: Literal["publish"]
    wordpress_url: str
    featured_media: int
    audit_id: int
    gate_results: list[WordPressDraftGateResult]


class WordPressFeaturedImageVerification(SQLModel):
    page_id: int
    wordpress_post_id: int
    wordpress_media_id: int
    post_status: str | None = None
    post_slug: str | None = None
    post_url: str | None = None
    featured_media: int | None = None
    media_31: WordPressMediaReconciliationCandidate | None = None
    media_32: WordPressMediaReconciliationCandidate | None = None
    gate_results: list[WordPressDraftGateResult]
    status: Literal["verified", "failed"]
    ready: bool = False
    apply_needed: bool
    featured_image_correct: bool
    confirmation_token: None = None
    confirmation_phrase: None = None
    read_only: bool = True


class WordPressDraftCreateRequest(SQLModel):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=300)


class WordPressDraftCreateResult(SQLModel):
    page_id: int
    status: Literal["created"]
    wordpress_post_id: int
    wordpress_status: Literal["draft"]
    wordpress_url: str | None = None
    audit_id: int
    payload_hash: str
    gate_results: list[WordPressDraftGateResult]


class WordPressDraftReviewItem(SQLModel):
    page_id: int
    page_title: str
    city: str | None = None
    county: str | None = None
    service: str | None = None
    atlas_status: str
    qa_status: str
    wordpress_post_id: int
    wordpress_status: str | None = None
    wordpress_url: str | None = None
    last_wordpress_sync_at: str | None = None
    successful_draft_audit_count: int = 0
    latest_draft_audit_at: str | None = None
    audit_payload_hash: str | None = None
    audit_draft_hash: str | None = None
    admin_edit_url: str | None = None
    badges: list[str] = []


class WordPressDraftReviewList(SQLModel):
    total_count: int
    items: list[WordPressDraftReviewItem]


class WordPressLiveDraftStatus(SQLModel):
    page_id: int
    wordpress_post_id: int
    rest_api_reachable: bool | None = None
    authenticated: bool | None = None
    credentials_present: bool = False
    wordpress_status: str | None = None
    wordpress_link: str | None = None
    wordpress_modified: str | None = None
    wordpress_title: str | None = None
    wordpress_slug: str | None = None
    is_still_draft: bool = False
    appears_published: bool = False
    error_message: str | None = None


class WordPressDraftComparison(SQLModel):
    page_id: int
    atlas_saved_title: str
    wordpress_title: str | None = None
    atlas_saved_slug: str
    wordpress_slug: str | None = None
    atlas_expected_status: Literal["draft"] = "draft"
    wordpress_actual_status: str | None = None
    atlas_wordpress_url: str | None = None
    wordpress_link: str | None = None
    audit_payload_hash: str | None = None
    current_export_payload_hash: str
    audit_draft_hash: str | None = None
    atlas_export_differs_from_original: bool = False
    message: str | None = None


class WordPressDraftReviewDetail(SQLModel):
    item: WordPressDraftReviewItem
    comparison: WordPressDraftComparison


QualityCheckStatus = Literal["pass", "warning", "fail"]
QualityReadinessStatus = Literal["ready", "needs_review", "blocked"]
ManualQualityReviewStatus = Literal[
    "not_reviewed",
    "in_review",
    "needs_changes",
    "ready_for_manual_publish_review",
]


class WordPressQualityCheck(SQLModel):
    key: str
    label: str
    status: QualityCheckStatus
    message: str
    review_field: str


class WordPressManualQualityReviewRead(SQLModel):
    id: int | None = None
    generated_page_id: int
    review_status: ManualQualityReviewStatus = "not_reviewed"
    reviewer_notes: str | None = None
    reviewed_at: datetime | None = None
    reviewed_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class WordPressManualQualityReviewUpdate(SQLModel):
    review_status: ManualQualityReviewStatus = "not_reviewed"
    reviewer_notes: str | None = Field(default=None, max_length=5000)
    reviewed_by: str | None = Field(default=None, max_length=200)

    @field_validator("reviewer_notes", "reviewed_by", mode="before")
    @classmethod
    def trim_optional_text(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return stripped or None


class WordPressDraftQualityReviewItem(SQLModel):
    page_id: int
    page_title: str
    city: str | None = None
    county: str | None = None
    service: str | None = None
    atlas_status: str
    qa_status: str
    wordpress_post_id: int
    wordpress_status: str | None = None
    wordpress_url: str | None = None
    admin_edit_url: str | None = None
    slug: str
    payload_hash_matches_audit: bool
    pass_count: int
    warning_count: int
    fail_count: int
    overall_publish_readiness: QualityReadinessStatus
    blockers_or_issues: list[str] = []
    safe_for_future_manual_review: bool
    manual_review: WordPressManualQualityReviewRead
    checklist: list[WordPressQualityCheck]


class WordPressDraftQualityReviewList(SQLModel):
    total_count: int
    ready_count: int
    needs_review_count: int
    blocked_count: int
    items: list[WordPressDraftQualityReviewItem]


class WordPressDraftQueueItem(SQLModel):
    page_id: int
    page_title: str
    city: str | None = None
    county: str | None = None
    service: str | None = None
    atlas_status: str
    qa_status: str
    qa_checked_at: str | None = None
    revision_count: int = 0
    latest_revision_at: str | None = None
    approval_audit_count: int = 0
    export_ready: bool = False
    export_blocker_count: int = 0
    export_warning_count: int = 0
    slug: str
    slug_conflicts: list[int] = []
    wordpress_post_id: int | None = None
    wordpress_status: str | None = None
    wordpress_url: str | None = None
    payload_status: Literal["draft"] = "draft"
    queue_group: Literal[
        "eligible",
        "blocked_approval",
        "blocked_qa",
        "blocked_stale_qa",
        "blocked_missing_media",
        "already_has_draft",
        "blocked_credentials",
        "blocked_export",
    ]
    eligible: bool = False
    gate_results: list[WordPressDraftGateResult] = []
    next_required_action: str


class WordPressDraftQueueResponse(SQLModel):
    total_count: int
    eligible_count: int
    blocked_count: int
    already_has_draft_count: int
    wordpress_mode: PublishingMode
    has_application_password: bool
    site_url_configured: bool
    username_configured: bool
    items: list[WordPressDraftQueueItem]


class WordPressMetadataPayload(SQLModel):
    schema_version: Literal["1.0"] = "1.0"
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    meta_description: str
    open_graph: dict[str, str]
    twitter: dict[str, str]
    json_ld: dict[str, Any]
    media_id: Literal[31] = 31
    excluded_media_ids: list[int] = [32]


class WordPressMetadataLifecyclePayload(SQLModel):
    """Exact v0.59.54 staging payload; it intentionally contains no media fields."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    meta_description: str
    json_ld: dict[str, Any]


class WordPressMetadataBackupProof(SQLModel):
    confirmed_data_backup_file: str = Field(min_length=1, max_length=255)
    confirmed_media_backup_identity: str = Field(min_length=1, max_length=255)
    confirmed_program_backup_identity: str = Field(min_length=1, max_length=255)
    wordpress_backup_reference: str = Field(min_length=1, max_length=255)
    wordpress_backup_timestamp: datetime
    wordpress_backup_database_included: bool
    wordpress_backup_plugin_files_included: bool
    wordpress_restore_capability_confirmed: bool


class WordPressMetadataDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["blocked", "metadata_ready"]
    ready: bool
    plugin_version: str
    plugin_installed: bool
    plugin_active: bool
    plugin_rendering_enabled: bool
    payload: WordPressMetadataPayload
    payload_hash: str
    current_snapshot: dict[str, Any] | None = None
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    dry_run_only: bool = True
    bound_state_hash: str | None = None


class WordPressMetadataApplyRequest(WordPressMetadataBackupProof):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)


class WordPressMetadataApplyResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["metadata_applied"]
    payload_hash: str
    wordpress_revision: str
    audit_id: int
    verification: dict[str, Any]


class WordPressMetadataVerification(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["verified", "failed", "not_applied"]
    ready: Literal[False] = False
    apply_needed: bool
    metadata_correct: bool
    payload_hash: str
    live_payload_hash: str | None = None
    rendered: dict[str, Any] | None = None
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: None = None
    confirmation_phrase: None = None
    read_only: Literal[True] = True


class WordPressMetadataRollbackDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["blocked", "rollback_ready"]
    ready: bool
    current_payload_hash: str | None = None
    restore_snapshot: dict[str, Any] | None = None
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    successful_apply_audit_id: int | None = None
    bound_state_hash: str | None = None


class WordPressMetadataRollbackRequest(WordPressMetadataBackupProof):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)


class WordPressMetadataRollbackResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["metadata_rolled_back"]
    audit_id: int
    wordpress_revision: str


class WordPressMetadataReconciliationDryRun(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["blocked", "safe_to_finalize"]
    safe_to_finalize: bool
    original_audit_id: int | None = None
    verification: WordPressMetadataVerification
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    read_only: Literal[True] = True


class WordPressMetadataReconciliationRequest(WordPressMetadataBackupProof):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=200)


class WordPressMetadataReconciliationResult(SQLModel):
    page_id: int
    wordpress_post_id: int
    status: Literal["metadata_reconciled"]
    original_audit_id: int
    wordpress_write_performed: Literal[False] = False


class WordPressManualBrowserEvidence(SQLModel):
    """Strict signed envelope; nested values are independently validated by the evidence service."""

    model_config = ConfigDict(extra="forbid")

    evidence_schema: Literal["project-atlas-manual-browser-evidence"]
    evidence_schema_version: Literal[1, 2]
    capture_helper_version: Literal["0.59.80"]
    evidence_id: str = Field(min_length=8, max_length=200)
    captured_at: str = Field(min_length=27, max_length=27)
    expires_at: str = Field(min_length=27, max_length=27)
    final_url: str
    acquisition_source: Literal["credential_free_public_browser"]
    navigation_outcome: dict[str, Any]
    page_identity: dict[str, Any]
    metadata_inventory: dict[str, Any]
    metadata_inventory_hash: str = Field(min_length=64, max_length=64)
    absence_findings: dict[str, bool]
    normalized_head: str = Field(min_length=1, max_length=500_000)
    normalized_visible_content: str = Field(min_length=1, max_length=2_000_000)
    rendered_head_hash: str = Field(min_length=64, max_length=64)
    visible_content_hash: str = Field(min_length=64, max_length=64)
    privacy_attestations: dict[str, bool]
    h1_inventory: list[dict[str, Any]] | None = None
    h1_count: int | None = None
    primary_h1: str | None = None
    body_h1: str | None = None
    helper_signature: str = Field(min_length=64, max_length=64)


class WordPressDeploymentBackupEvidence(SQLModel):
    atlas_data_backup_file: str = Field(min_length=6, max_length=255)
    atlas_media_backup_file: str = Field(min_length=6, max_length=255)
    atlas_program_backup_file: str = Field(min_length=6, max_length=255)
    wordpress_backup_method: str = Field(min_length=6, max_length=255)
    wordpress_backup_reference: str = Field(min_length=6, max_length=255)
    wordpress_backup_completed_at: datetime
    wordpress_database_included_attestation: bool
    wordpress_plugins_included_attestation: bool
    wordpress_restore_capability_attestation: bool
    confirmer_identity: str = Field(min_length=3, max_length=200)
    php_error_log_findings: str = Field(min_length=3, max_length=2000)
    observed_write_summary: str = Field(min_length=3, max_length=2000)
    manual_browser_evidence: WordPressManualBrowserEvidence | None = None


class WordPressDeploymentPreflightRequest(WordPressDeploymentBackupEvidence):
    model_config = ConfigDict(extra="forbid")


class WordPressDeploymentPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["preflight_blocked", "preflight_ready"]
    preflight_ready: bool
    backup_age_seconds: int | None = None
    backup_deadline: datetime | None = None
    artifact: dict[str, Any]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    php_error_findings: dict[str, Any]
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    nonce_consumed: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0
    read_only: Literal[True] = True


class WordPressDeploymentInstallDryRun(SQLModel):
    page_id: int = 41
    wordpress_post_id: int = 8
    status: Literal["preflight_not_started", "preflight_ready"]
    ready: bool
    artifact: dict[str, Any]
    inspected_state: dict[str, Any]
    backup_age_seconds: int | None = None
    gate_results: list[WordPressDraftGateResult]
    confirmation_token: str | None = None
    confirmation_phrase: str | None = None
    expires_at: str | None = None
    read_only: Literal[True] = True


class WordPressDeploymentAuthorizeRequest(WordPressDeploymentBackupEvidence):
    confirmation_token: str = Field(min_length=1)
    confirmation_phrase: str = Field(min_length=1, max_length=100)
    operator: str = Field(min_length=3, max_length=200)
    shawn_approved_at: datetime
    evidence_directory: str = Field(min_length=10, max_length=500)


class WordPressDeploymentAuthorization(SQLModel):
    audit_id: int
    status: Literal["awaiting_manual_installation"]
    installation_transport: Literal["manual_wordpress_admin_upload"] = "manual_wordpress_admin_upload"
    zip_file_name: str
    zip_sha256: str
    instructions: list[str]
    warning: Literal["DO NOT CLICK ACTIVATE PLUGIN"] = "DO NOT CLICK ACTIVATE PLUGIN"
    wordpress_request_performed: Literal[False] = False
    state_history: list[str]


class WordPressDeploymentManualCompleteRequest(SQLModel):
    audit_id: int
    operator: str = Field(min_length=3, max_length=200)
    manual_upload_completed_attestation: bool


class WordPressDeploymentManualComplete(SQLModel):
    audit_id: int
    status: Literal["verification_pending"]
    success_assumed: Literal[False] = False
    wordpress_request_performed: Literal[False] = False
    state_history: list[str]


class WordPressDeploymentVerification(SQLModel):
    audit_id: int
    status: Literal["verified", "verification_failed", "reconciliation_required"]
    verified: bool
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    read_only_wordpress: Literal[True] = True
    state_history: list[str]
    inspection_limitations: list[str] = Field(default_factory=list)


class WordPressDeploymentVerifyRequest(SQLModel):
    audit_id: int
    operator: str = Field(min_length=3, max_length=200)
    php_error_log_findings: str = Field(min_length=3, max_length=2000)


class WordPressDeploymentExpectedRuntimeIdentity(SQLModel):
    model_config = ConfigDict(extra="forbid")

    atlas_version: str = Field(min_length=2, max_length=32)
    atlas_commit: str = Field(min_length=40, max_length=40)
    atlas_tag: str = Field(min_length=2, max_length=32)
    manifest_sha256: str = Field(min_length=64, max_length=64)
    source_compatibility_id: str = Field(min_length=3, max_length=200)

    @field_validator("atlas_commit", "manifest_sha256")
    @classmethod
    def validate_lower_hex(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]+", value) is None:
            raise ValueError("Release hashes must be lowercase hexadecimal.")
        return value


class WordPressDeploymentReconciliationVerifyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: int = Field(gt=0)
    manual_browser_evidence: WordPressManualBrowserEvidence
    expected_plugin_slug: str = Field(min_length=3, max_length=100)
    expected_plugin_path: str = Field(min_length=3, max_length=255)
    expected_plugin_version: str = Field(min_length=1, max_length=32)
    expected_zip_sha256: str = Field(min_length=64, max_length=64)
    expected_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_active_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_page_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_body_hash: str = Field(min_length=64, max_length=64)
    expected_media31_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_media32_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity

    @field_validator(
        "expected_zip_sha256",
        "expected_plugin_inventory_hash",
        "expected_active_plugin_inventory_hash",
        "expected_page_snapshot_hash",
        "expected_body_hash",
        "expected_media31_snapshot_hash",
        "expected_media32_snapshot_hash",
    )
    @classmethod
    def validate_lower_hex(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValueError("Expected hashes must be 64 lowercase hexadecimal characters.")
        return value


class WordPressDeploymentReconciliationVerification(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    audit_id: int
    status: Literal["reconciliation_blocked", "reconciliation_ready"]
    reconciliation_ready: bool
    reconciliation_handle: str | None = None
    confirmation_phrase: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    proposed_atlas_changes: list[str]
    inspection_only: Literal[True] = True
    installation_token_issued: Literal[False] = False
    installation_nonce_consumed: Literal[False] = False
    deployment_audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressDeploymentReconciliationApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class WordPressDeploymentReconciliationResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    audit_id: int
    status: Literal["verified"]
    completion_mode: Literal["installed_inactive_reconciliation"] = "installed_inactive_reconciliation"
    binding_hash: str
    state_history: list[str]
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[2] = 2
    original_authorization_nonce_preserved: Literal[True] = True
    original_transition_history_preserved: Literal[True] = True
    further_reconciliation_required: Literal[False] = False


class WordPressActivationPreflightRequest(WordPressDeploymentBackupEvidence):
    """Complete immutable input contract for activation inspection."""

    model_config = ConfigDict(extra="forbid")

    installation_audit_id: int = Field(gt=0)
    operator: str = Field(min_length=3, max_length=200)
    expected_plugin_slug: str = Field(min_length=3, max_length=100)
    expected_plugin_path: str = Field(min_length=3, max_length=255)
    expected_plugin_version: str = Field(min_length=1, max_length=32)
    expected_zip_sha256: str = Field(min_length=64, max_length=64)
    expected_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_active_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_page_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_body_hash: str = Field(min_length=64, max_length=64)
    expected_media31_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_media32_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity
    repository_head: str = Field(min_length=40, max_length=40)
    repository_origin_main: str = Field(min_length=40, max_length=40)
    repository_tag: str = Field(min_length=2, max_length=32)
    repository_working_tree_clean: bool
    protected_paths_unchanged: bool
    no_relevant_wordpress_change_after_backup: bool
    browser_console_findings: str = Field(min_length=3, max_length=2000)

    @field_validator(
        "expected_zip_sha256",
        "expected_plugin_inventory_hash",
        "expected_active_plugin_inventory_hash",
        "expected_page_snapshot_hash",
        "expected_body_hash",
        "expected_media31_snapshot_hash",
        "expected_media32_snapshot_hash",
        "repository_head",
        "repository_origin_main",
    )
    @classmethod
    def validate_activation_hashes(cls, value: str) -> str:
        expected_length = 40 if len(value) == 40 else 64
        if len(value) != expected_length or re.fullmatch(r"[0-9a-f]+", value) is None:
            raise ValueError("Activation identity hashes must be lowercase hexadecimal.")
        return value


class WordPressActivationPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    installation_audit_id: int
    status: Literal["activation_preflight_blocked", "activation_preflight_ready"]
    activation_preflight_ready: bool
    activation_handle: str | None = None
    activation_handle_fingerprint: str | None = None
    confirmation_phrase: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    backup_deadline: datetime | None = None
    artifact: dict[str, Any]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    proposed_wordpress_write_scope: list[str]
    proposed_atlas_write_scope: list[str]
    expected_post_plugin_inventory_hash: str | None = None
    expected_post_active_plugin_inventory_hash: str | None = None
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    nonce_consumed: Literal[False] = False
    activation_audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressActivationApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    activation_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class WordPressActivationResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    installation_audit_id: int
    activation_audit_id: int
    status: Literal["verified", "verification_failed", "failed"]
    completion_mode: Literal["guarded_metadata_bridge_activation"] = "guarded_metadata_bridge_activation"
    binding_hash: str
    state_history: list[str]
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: Literal[1] = 1
    wordpress_write_scope: list[str]
    atlas_write_count: Literal[2] = 2
    atlas_write_scope: list[str]
    metadata_application_authorized: Literal[False] = False
    cache_purge_count: Literal[0] = 0
    further_action_required: bool


class WordPressPluginUpgradePreflightRequest(WordPressDeploymentBackupEvidence):
    """Immutable proof for one explicitly supported fixed bridge-upgrade profile."""

    model_config = ConfigDict(extra="forbid")

    installation_audit_id: int = Field(gt=0)
    activation_audit_id: int = Field(gt=0)
    operator: str = Field(min_length=3, max_length=200)
    current_plugin_version: Literal["0.57.4", "0.57.5", "0.57.6"]
    target_plugin_version: Literal["0.57.5", "0.57.6", "0.57.7"]
    current_plugin_slug: Literal["project-atlas-metadata-bridge"]
    current_plugin_path: Literal["project-atlas-metadata-bridge/project-atlas-metadata-bridge.php"]
    current_zip_filename: Literal["project-atlas-metadata-bridge-0.57.4.zip", "project-atlas-metadata-bridge-0.57.5.zip", "project-atlas-metadata-bridge-0.57.6.zip"]
    current_zip_sha256: Literal["939412e6e80e8344d95274444fda65b6122fe0c8249a2ced0a8582a418c4e232", "09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7", "3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788"]
    target_zip_filename: Literal["project-atlas-metadata-bridge-0.57.5.zip", "project-atlas-metadata-bridge-0.57.6.zip", "project-atlas-metadata-bridge-0.57.7.zip"]
    target_zip_sha256: Literal["09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7", "3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788", "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62"]
    previous_upgrade_audit_id: int | None = Field(default=None, gt=0)
    bootstrap_cleanup_audit_id: int | None = Field(default=None, gt=0)
    staging_audit_id: int | None = Field(default=None, gt=0)
    recovery_disable_audit_id: int | None = Field(default=None, gt=0)
    expected_payload_hash: str | None = Field(default=None, min_length=64, max_length=64)
    expected_revision: str | None = Field(default=None, max_length=40)
    expected_metadata_state_status: str | None = Field(default=None, max_length=40)
    expected_metadata_state_rows: int | None = Field(default=None, ge=0)
    expected_metadata_sync_audit_rows: int | None = Field(default=None, ge=0)
    expected_cache_purge_count: int | None = Field(default=None, ge=0)
    expected_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_active_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_post_plugin_inventory_hash: str | None = Field(default=None, min_length=64, max_length=64)
    expected_post_active_plugin_inventory_hash: str | None = Field(default=None, min_length=64, max_length=64)
    expected_page_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_body_hash: str = Field(min_length=64, max_length=64)
    expected_media31_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_media32_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity
    repository_head: str = Field(min_length=40, max_length=40)
    repository_origin_main: str = Field(min_length=40, max_length=40)
    repository_tag: str = Field(min_length=2, max_length=32)
    repository_branch: Literal["main"]
    repository_working_tree_clean: bool
    protected_paths_unchanged: bool
    no_relevant_wordpress_change_after_backup: bool
    browser_console_findings: str = Field(min_length=3, max_length=2000)

    @field_validator(
        "expected_plugin_inventory_hash",
        "expected_active_plugin_inventory_hash",
        "expected_post_plugin_inventory_hash",
        "expected_post_active_plugin_inventory_hash",
        "expected_page_snapshot_hash",
        "expected_body_hash",
        "expected_media31_snapshot_hash",
        "expected_media32_snapshot_hash",
        "expected_payload_hash",
        "repository_head",
        "repository_origin_main",
    )
    @classmethod
    def validate_upgrade_hashes(cls, value: str | None) -> str | None:
        if value is None:
            return value
        expected_length = 40 if len(value) == 40 else 64
        if len(value) != expected_length or re.fullmatch(r"[0-9a-f]+", value) is None:
            raise ValueError("Plugin-upgrade identity hashes must be lowercase hexadecimal.")
        return value


class WordPressPluginUpgradePreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["plugin_upgrade_preflight_blocked", "plugin_upgrade_preflight_ready"]
    plugin_upgrade_preflight_ready: bool
    upgrade_handle: str | None = None
    upgrade_handle_fingerprint: str | None = None
    confirmation_phrase: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    backup_deadline: datetime | None = None
    current_version: Literal["0.57.4", "0.57.5", "0.57.6"] = "0.57.4"
    target_version: Literal["0.57.5", "0.57.6", "0.57.7"] = "0.57.5"
    artifact: dict[str, Any]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    proposed_wordpress_write_scope: list[str]
    proposed_atlas_write_scope: list[str]
    expected_post_plugin_inventory_hash: str | None = None
    expected_post_active_plugin_inventory_hash: str | None = None
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    nonce_returned: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressPluginUpgradeApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    upgrade_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=120)


class WordPressPluginUpgradeResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    upgrade_audit_id: int
    status: Literal["verified", "verification_failed", "failed"]
    binding_hash: str
    state_history: list[str]
    previous_version: Literal["0.57.4", "0.57.5", "0.57.6"] = "0.57.4"
    target_version: Literal["0.57.5", "0.57.6", "0.57.7"] = "0.57.5"
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: Literal[1] = 1
    wordpress_write_scope: list[str]
    atlas_write_count: Literal[2] = 2
    atlas_write_scope: list[str]
    recovery_recommendation: Literal["no_action", "guarded_downgrade", "siteground_restore"]
    metadata_application_authorized: Literal[False] = False
    rendering_change_authorized: Literal[False] = False
    cache_purge_count: Literal[0] = 0
    further_action_required: bool


class WordPressPluginUpgradeRecoveryRequest(WordPressDeploymentBackupEvidence):
    model_config = ConfigDict(extra="forbid")

    upgrade_audit_id: int = Field(gt=0)


class WordPressPluginUpgradeRecoveryAssessment(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    upgrade_audit_id: int
    status: Literal["recovery_assessment_complete", "recovery_assessment_blocked"]
    recommendation: Literal["no_action", "guarded_downgrade", "siteground_restore"]
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0
    automatic_recovery_performed: Literal[False] = False


class WordPressBootstrapManualInstallPreflightRequest(WordPressPluginUpgradePreflightRequest):
    """The fixed 0.3.0 manual-upload proof; no artifact selector is accepted."""


class WordPressBootstrapManualInstallAuthorizeRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    manual_install_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=120)


class WordPressBootstrapManualInstallVerifyRequest(WordPressPluginUpgradePreflightRequest):
    model_config = ConfigDict(extra="forbid")

    establishment_audit_id: int = Field(gt=0)


class WordPressBootstrapActivationApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    activation_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=120)


class WordPressBootstrapAuthorizationRetirementRequest(SQLModel):
    """Read-only binding for retiring one stale pre-activation authorization.

    Retirement deliberately does not accept browser evidence or backup proof:
    those belong to the later, distinct fresh-authorization lifecycle.
    """

    model_config = ConfigDict(extra="forbid")

    establishment_audit_id: int = Field(gt=0)
    retirement_reason: Literal["manual_install_verification_genuine_transport_drift"]
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity


class WordPressBootstrapAuthorizationRetirementApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    retirement_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=180)


class WordPressBootstrapAuthorizationRetirementPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    ready: bool
    status: str
    current_status: str
    retirement_reason: str
    transport_comparison: dict[str, Any]
    expected_transition: list[str]
    expected_history_append: Literal["authorization_retired"] = "authorization_retired"
    expected_atlas_write_count: Literal[1] = 1
    confirmation_phrase: str | None = None
    retirement_handle: str | None = None
    handle_fingerprint: str | None = None
    expires_at: datetime | None = None
    gate_results: list[WordPressDraftGateResult]
    wordpress_write_count: Literal[0] = 0
    plugin_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressBootstrapAuthorizationRetirementResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    status: Literal["authorization_retired"] = "authorization_retired"
    retirement_reason: Literal["manual_install_verification_genuine_transport_drift"]
    state_history: list[str]
    renewal_history: list[dict[str, Any]]
    authorization_snapshot_preserved: bool
    verification_evidence_present: bool
    activation_handle_present: bool
    checksum_quarantine_active: bool
    pending_operation: bool
    idempotent_replay: bool = False
    wordpress_write_count: Literal[0] = 0
    plugin_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    request_atlas_write_count: int = Field(default=0, ge=0)
    atlas_write_count: int = Field(ge=0)
    fresh_authorization_permitted: bool


class WordPressBootstrapInstalledInactiveAuthorizeRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    installed_bootstrap_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=180)


class WordPressBootstrapBackupRenewalRequest(SQLModel):
    """Minimum caller contract for one Atlas-only SiteGround backup renewal."""

    model_config = ConfigDict(extra="forbid")

    establishment_audit_id: int = Field(gt=0)
    atlas_data_backup_file: str = Field(min_length=6, max_length=255)
    atlas_media_backup_file: str = Field(min_length=6, max_length=255)
    atlas_program_backup_file: str = Field(min_length=6, max_length=255)
    replacement_backup_method: str = Field(min_length=6, max_length=255)
    replacement_backup_reference: str = Field(min_length=3, max_length=255)
    replacement_backup_completed_at: datetime
    replacement_backup_deadline: datetime
    database_included_attestation: bool
    plugins_included_attestation: bool
    restore_capability_attestation: bool
    no_relevant_wordpress_change_after_backup: bool
    confirmer_identity: str = Field(min_length=3, max_length=200)


class WordPressBootstrapBackupRenewalApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    renewal_handle_fingerprint: str = Field(min_length=64, max_length=64)
    confirmation_phrase: str = Field(min_length=1, max_length=160)


class WordPressBootstrapBackupRenewalRecoveryRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    establishment_audit_id: int = Field(gt=0)


class WordPressBootstrapBackupRenewalPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    status: str
    ready: bool
    reason_code: str
    renewal_handle_fingerprint: str | None = None
    expires_at: datetime | None = None
    confirmation_phrase: str | None = None
    original_backup: dict[str, Any]
    active_backup: dict[str, Any]
    proposed_replacement: dict[str, Any]
    renewal_sequence: int
    gate_results: list[WordPressDraftGateResult]
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressBootstrapBackupRenewalResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    status: str
    reason_code: str
    renewal_sequence: int
    original_backup: dict[str, Any]
    active_backup: dict[str, Any]
    renewal_history: list[dict[str, Any]]
    state_history: list[str]
    idempotent_replay: bool = False
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    request_atlas_write_count: int = Field(default=0, ge=0)
    atlas_write_count: int
    recovery_recommendation: str


class WordPressBootstrapBackupRenewalRecovery(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    status: Literal["recovery_assessment_complete"] = "recovery_assessment_complete"
    audit_status: str
    classification: str
    reason_code: str
    recommendation: Literal[
        "create_fresh_siteground_backup", "run_guarded_backup_renewal",
        "proceed_to_manual_verification", "renew_backup_again",
        "new_manual_authorization_required", "guarded_bootstrap_recovery",
        "siteground_restore", "no_action",
    ]
    next_required_action: str
    renewal_eligible: bool
    renewal_blocked: bool
    original_backup: dict[str, Any]
    original_backup_expired: bool | None
    original_backup_expiration_status: Literal["valid", "expired", "missing", "invalid"]
    original_backup_remaining_seconds: int | None = Field(default=None, ge=0)
    active_backup: dict[str, Any]
    active_backup_source: Literal["original", "replacement", "none"]
    active_backup_expired: bool | None
    active_backup_expiration_status: Literal["valid", "expired", "missing", "invalid"]
    active_backup_remaining_seconds: int | None = Field(default=None, ge=0)
    active_renewal_sequence: int | None = Field(default=None, ge=1)
    renewal_history: list[dict[str, Any]]
    renewal_count: int = Field(ge=0)
    maximum_renewals: int = Field(ge=1)
    renewals_remaining: int = Field(ge=0)
    renewal_limit_reached: bool
    bootstrap_manually_uploaded: bool | None
    verification_evidence_present: bool
    activation_started: bool
    checksum_quarantine_active: bool
    pending_operation: bool
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressBootstrapEstablishmentPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    stage: str
    ready: bool
    status: str
    establishment_audit_id: int | None = None
    handle: str | None = None
    handle_fingerprint: str | None = None
    binding_hash: str | None = None
    confirmation_phrase: str | None = None
    expires_at: datetime | None = None
    backup_deadline: datetime | None = None
    artifact: dict[str, Any]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    instructions: list[str] = Field(default_factory=list)
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressBootstrapEstablishmentResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    stage: str
    status: str
    state_history: list[str]
    binding_hash: str
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: int
    wordpress_write_scope: list[str]
    cache_write_count: Literal[0] = 0
    atlas_write_count: int
    atlas_write_scope: list[str]
    request_atlas_write_count: int = Field(default=0, ge=0)
    idempotent_replay: bool = False
    reason_code: str = "bootstrap_establishment_result"
    authorization_evidence: dict[str, Any] = Field(default_factory=dict)
    verification_evidence: dict[str, Any] | None = None
    stable_evidence_match: bool = False
    fresh_evidence_required: bool = False
    backup_deadline_valid: bool = False
    original_backup: dict[str, Any] = Field(default_factory=dict)
    active_backup: dict[str, Any] = Field(default_factory=dict)
    backup_renewals: list[dict[str, Any]] = Field(default_factory=list)
    recovery_recommendation: str
    further_action_required: bool


class WordPressBootstrapRecoveryAssessment(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: int
    status: Literal["recovery_assessment_complete", "recovery_assessment_blocked"]
    classification: str
    recommendation: Literal["no_action", "proceed_to_bridge_upgrade", "guarded_bootstrap_recovery", "guarded_bootstrap_cleanup", "retry_from_fresh_backup", "siteground_restore"]
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0
    automatic_recovery_performed: Literal[False] = False


class WordPressBootstrapActivationReconciliationRequest(SQLModel):
    """Fresh read-only proof for reconciling the exact v0.59.92 activation result."""

    model_config = ConfigDict(extra="forbid")

    establishment_audit_id: Literal[2]
    operator: str = Field(min_length=3, max_length=200)
    manual_browser_evidence: WordPressManualBrowserEvidence
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity
    repository_head: str = Field(min_length=40, max_length=40)
    repository_origin_main: str = Field(min_length=40, max_length=40)
    repository_tag: Literal["v0.59.95"]
    repository_branch: Literal["main"]
    repository_working_tree_clean: bool
    protected_paths_unchanged: bool
    atlas_data_backup_file: str = Field(min_length=6, max_length=255)
    atlas_data_backup_sha256: str = Field(min_length=64, max_length=64)
    atlas_data_backup_size: int = Field(gt=0)
    atlas_data_backup_created_at: datetime
    atlas_data_backup_onedrive_path: str = Field(min_length=10, max_length=1000)
    atlas_data_backup_onedrive_synced: bool

    @field_validator(
        "repository_head",
        "repository_origin_main",
        "atlas_data_backup_sha256",
    )
    @classmethod
    def validate_reconciliation_hashes(cls, value: str) -> str:
        if re.fullmatch(r"[0-9a-f]+", value) is None:
            raise ValueError("Reconciliation hashes must be lowercase hexadecimal.")
        return value


class WordPressBootstrapActivationReconciliationPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: Literal[2] = 2
    status: Literal[
        "bootstrap_activation_reconciliation_blocked",
        "bootstrap_activation_reconciliation_ready",
    ]
    reconciliation_ready: bool
    reconciliation_handle: str | None = None
    reconciliation_handle_fingerprint: str | None = None
    binding_hash: str | None = None
    confirmation_phrase: str | None = None
    expires_at: datetime | None = None
    expected_final_status: Literal["verified"] = "verified"
    expected_history_append: Literal[
        "post_activation_verifier_contract_defect_reconciled"
    ] = "post_activation_verifier_contract_defect_reconciled"
    expected_wordpress_write_count: Literal[0] = 0
    expected_plugin_write_count: Literal[0] = 0
    expected_cache_write_count: Literal[0] = 0
    expected_atlas_write_count: Literal[1] = 1
    atlas_data_backup: dict[str, Any]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    inspection_only: Literal[True] = True
    audit_created: Literal[False] = False


class WordPressBootstrapActivationReconciliationApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    reconciliation_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=160)


class WordPressBootstrapActivationReconciliationResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    establishment_audit_id: Literal[2] = 2
    status: Literal["verified"] = "verified"
    reconciliation_reason: Literal[
        "post_activation_verifier_contract_defect_reconciled"
    ] = "post_activation_verifier_contract_defect_reconciled"
    state_history: list[str]
    binding_hash: str
    reconciliation_handle_fingerprint: str
    wordpress_write_count: Literal[0] = 0
    plugin_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    request_atlas_write_count: Literal[0, 1]
    cumulative_atlas_write_count: int = Field(ge=0)
    original_activation_write_count: Literal[1] = 1
    original_activation_write_preserved: Literal[True] = True
    original_failure_history_preserved: Literal[True] = True
    new_audit_created: Literal[False] = False
    new_authorization_created: Literal[False] = False
    idempotent_replay: bool = False
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    further_action_required: Literal[False] = False


class WordPressBootstrapCleanupPreflightRequest(WordPressDeploymentBackupEvidence):
    """Immutable proof for deactivating the fixed upgrade bootstrap."""

    model_config = ConfigDict(extra="forbid")

    installation_audit_id: Literal[1]
    activation_audit_id: Literal[1]
    upgrade_audit_id: int = Field(gt=0)
    operator: str = Field(min_length=3, max_length=200)
    expected_bridge_slug: Literal["project-atlas-metadata-bridge"]
    expected_bridge_path: Literal["project-atlas-metadata-bridge/project-atlas-metadata-bridge.php"]
    expected_bridge_version: Literal["0.57.5", "0.57.6", "0.57.7"]
    expected_bridge_zip_sha256: Literal["09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7", "3b2d0035f995c3006e0d3be02596bd2cf19ef7e4a97572168621beb7a9abf788", "ada4d97ea627a148d07fda809c1776a91a87d7a7e4957de3bece423a9bb80a62"]
    expected_bootstrap_slug: Literal["project-atlas-upgrade-bootstrap"]
    expected_bootstrap_path: Literal["project-atlas-upgrade-bootstrap/project-atlas-upgrade-bootstrap.php"]
    expected_bootstrap_version: Literal["0.1.0", "0.2.0", "0.3.0"]
    expected_bootstrap_zip_sha256: Literal["4c8b4b0c697b2b352a10f405950c7b6a750236be96aec81fcd45176ece1189bd", "873701da2ed42212e7d7c9b12816eeb0560d2751d7494c2b706008c0d5c1383a", "de5bfb7875b6f84f2009ef2043c1c86c7f9d20f0f973a5cb16b478fe37e83bef"]
    expected_payload_hash: str | None = Field(default=None, min_length=64, max_length=64)
    expected_revision: str | None = Field(default=None, max_length=40)
    expected_metadata_state_status: str | None = Field(default=None, max_length=40)
    expected_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_active_plugin_inventory_hash: str = Field(min_length=64, max_length=64)
    expected_page_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_body_hash: str = Field(min_length=64, max_length=64)
    expected_media31_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_media32_snapshot_hash: str = Field(min_length=64, max_length=64)
    expected_runtime_identity: WordPressDeploymentExpectedRuntimeIdentity
    repository_head: str = Field(min_length=40, max_length=40)
    repository_origin_main: str = Field(min_length=40, max_length=40)
    repository_tag: str = Field(min_length=2, max_length=32)
    repository_branch: Literal["main"]
    repository_working_tree_clean: bool
    protected_paths_unchanged: bool
    no_relevant_wordpress_change_after_backup: bool
    browser_console_findings: str = Field(min_length=3, max_length=2000)

    @field_validator(
        "expected_plugin_inventory_hash",
        "expected_active_plugin_inventory_hash",
        "expected_page_snapshot_hash",
        "expected_body_hash",
        "expected_media31_snapshot_hash",
        "expected_media32_snapshot_hash",
        "expected_payload_hash",
        "repository_head",
        "repository_origin_main",
    )
    @classmethod
    def validate_cleanup_hashes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        length = 40 if len(value) == 40 else 64
        if len(value) != length or re.fullmatch(r"[0-9a-f]+", value) is None:
            raise ValueError("Bootstrap-cleanup identity hashes must be lowercase hexadecimal.")
        return value


class WordPressBootstrapDeletionPreflightRequest(WordPressBootstrapCleanupPreflightRequest):
    """Fresh proof for deleting one already-deactivated bootstrap."""

    cleanup_audit_id: int = Field(gt=0)


class WordPressBootstrapCleanupPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    phase: Literal["deactivation", "deletion"]
    status: Literal["bootstrap_cleanup_preflight_blocked", "bootstrap_cleanup_preflight_ready"]
    bootstrap_cleanup_preflight_ready: bool
    cleanup_handle: str | None = None
    cleanup_handle_fingerprint: str | None = None
    confirmation_phrase: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    backup_deadline: datetime | None = None
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    proposed_wordpress_write_scope: list[str]
    proposed_atlas_write_scope: list[str]
    expected_post_plugin_inventory_hash: str | None = None
    expected_post_active_plugin_inventory_hash: str | None = None
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    nonce_consumed: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressBootstrapCleanupApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    cleanup_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=120)


class WordPressBootstrapCleanupResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    cleanup_audit_id: int
    phase: Literal["deactivation", "deletion"]
    status: Literal["deactivated", "verified", "verification_failed", "failed"]
    binding_hash: str
    state_history: list[str]
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any]
    wordpress_write_count: int
    wordpress_write_scope: list[str]
    atlas_write_count: int
    atlas_write_scope: list[str]
    recovery_recommendation: Literal[
        "no_action",
        "guarded_reactivation",
        "guarded_reinstall",
        "siteground_restore",
    ]
    metadata_application_authorized: Literal[False] = False
    rendering_change_authorized: Literal[False] = False
    cache_purge_count: Literal[0] = 0
    further_action_required: bool


class WordPressMetadataLifecyclePreflightRequest(WordPressActivationPreflightRequest):
    """Immutable proof used by each isolated metadata lifecycle preflight."""

    model_config = ConfigDict(extra="forbid")

    activation_audit_id: int = Field(gt=0)
    candidate_payload: WordPressMetadataLifecyclePayload


class WordPressMetadataLifecyclePreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    action: Literal[
        "stage_metadata_payload",
        "enable_metadata_rendering",
        "disable_metadata_rendering",
        "rollback_metadata_payload",
    ]
    status: Literal["metadata_lifecycle_preflight_blocked", "metadata_lifecycle_preflight_ready"]
    preflight_ready: bool
    lifecycle_handle: str | None = None
    handle_fingerprint: str | None = None
    expires_at: datetime | None = None
    binding_hash: str | None = None
    confirmation_phrase: str | None = None
    canonical_payload: WordPressMetadataLifecyclePayload
    payload_sha256: str
    expected_revision: str
    completion_mode: Literal[
        "standard",
        "ordinary_after_verified_enable",
        "recovery_after_failed_enable_verification",
    ] = "standard"
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    proposed_wordpress_write_scope: list[str]
    proposed_atlas_write_scope: list[str]
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    nonce_issued: Literal[False] = False
    nonce_consumed: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressMetadataLifecycleApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")

    lifecycle_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class WordPressMetadataLifecycleResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    lifecycle_audit_id: int
    action: Literal[
        "stage_metadata_payload",
        "enable_metadata_rendering",
        "disable_metadata_rendering",
        "rollback_metadata_payload",
    ]
    status: Literal["verified", "verification_failed", "failed"]
    binding_hash: str
    state_history: list[str]
    completion_mode: Literal[
        "standard",
        "ordinary_after_verified_enable",
        "recovery_after_failed_enable_verification",
    ] = "standard"
    payload_hash: str
    wordpress_revision: str
    rendering_enabled: bool
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    wordpress_write_count: Literal[1] = 1
    wordpress_write_scope: list[str]
    atlas_write_count: Literal[2] = 2
    atlas_write_scope: list[str]
    cache_purge_count: Literal[0] = 0
    page_write_count: Literal[0] = 0
    media_write_count: Literal[0] = 0
    further_action_required: bool


class WordPressCacheAwareRenderingPreflightRequest(WordPressMetadataLifecyclePreflightRequest):
    """Locked proof for the disabled staged state and cache-aware orchestration."""

    model_config = ConfigDict(extra="forbid")
    staging_audit_id: int = Field(gt=0)
    recovery_disable_audit_id: int = Field(gt=0)


class WordPressCacheAwareRenderingPreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["cache_aware_rendering_preflight_blocked", "cache_aware_rendering_preflight_ready"]
    preflight_ready: bool
    rendering_handle: str | None = None
    handle_fingerprint: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    rendering_confirmation_phrase: str | None = None
    cache_confirmation_phrase: str | None = None
    proposed_wordpress_write_scope: list[str]
    proposed_cache_write_scope: list[str]
    proposed_atlas_write_scope: list[str]
    inspected_state: dict[str, Any]
    gate_results: list[WordPressDraftGateResult]
    inspection_only: Literal[True] = True
    token_issued: Literal[False] = False
    audit_created: Literal[False] = False
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressCacheAwareRenderingApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")
    rendering_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class WordPressCachePurgePreflightRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")
    cache_aware_audit_id: int = Field(gt=0)


class WordPressCachePurgePreflight(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    status: Literal["cache_purge_preflight_blocked", "cache_purge_preflight_ready"]
    preflight_ready: bool
    cache_handle: str | None = None
    handle_fingerprint: str | None = None
    binding_hash: str | None = None
    expires_at: datetime | None = None
    confirmation_phrase: str | None = None
    cache_provider: Literal["siteground_speed_optimizer"] = "siteground_speed_optimizer"
    cache_scope: Literal["single_canonical_url"] = "single_canonical_url"
    cache_target: str
    gate_results: list[WordPressDraftGateResult]
    inspected_state: dict[str, Any] = Field(default_factory=dict)
    inspection_only: Literal[True] = True
    wordpress_write_count: Literal[0] = 0
    cache_write_count: Literal[0] = 0
    atlas_write_count: Literal[0] = 0


class WordPressCachePurgeApplyRequest(SQLModel):
    model_config = ConfigDict(extra="forbid")
    cache_handle: str = Field(min_length=32, max_length=200)
    confirmation_phrase: str = Field(min_length=1, max_length=100)


class WordPressCacheAwareRenderingResult(SQLModel):
    page_id: Literal[41] = 41
    wordpress_post_id: Literal[8] = 8
    cache_aware_audit_id: int
    status: Literal[
        "pending_rendering", "origin_verified", "pending_cache_purge", "verified",
        "verification_failed", "failed",
    ]
    transition_history: list[str]
    payload_hash: str
    wordpress_revision: str
    rendering_enabled: bool
    cache_provider: str | None = None
    cache_scope: str | None = None
    cache_target: str | None = None
    reason_code: str
    gate_results: list[WordPressDraftGateResult]
    wordpress_write_count: int
    cache_write_count: int
    atlas_write_count: int
    wordpress_write_scope: list[str]
    cache_write_scope: list[str]
    atlas_write_scope: list[str]
    recovery_recommendation: str
    further_action_required: bool
