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
