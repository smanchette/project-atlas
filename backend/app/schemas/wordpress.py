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
    capture_helper_version: Literal["0.59.15"]
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
