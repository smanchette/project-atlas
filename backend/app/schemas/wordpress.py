from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import field_validator
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


class WordPressPayloadPreview(SQLModel):
    page_id: int
    export_package: dict[str, Any]
    payload: WordPressPayload
    warnings: list[dict[str, str]]
    sandbox_only: bool = True


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
