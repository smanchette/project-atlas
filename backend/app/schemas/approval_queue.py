from datetime import datetime
from typing import Literal

from sqlmodel import SQLModel


HeroImageStatus = Literal["missing", "unreviewed", "missing_alt_text", "reviewed"]


class ApprovalQueueItem(SQLModel):
    page_id: int
    page_title: str
    city_id: int | None = None
    city_name: str
    county_id: int | None = None
    county_name: str
    service_id: int
    service_name: str
    page_status: str
    qa_status: str
    qa_checked_at: datetime | None = None
    latest_revision_at: datetime | None = None
    revision_count: int
    approval_history_count: int
    hero_image_status: HeroImageStatus
    last_reviewed_at: datetime | None = None
    internal_notes_snippet: str | None = None
    is_ready_for_approval: bool
    has_blockers: bool
    has_warnings: bool
    edited_since_last_qa: bool
    approved_but_unpublished: bool
    missing_media: bool
    needs_manual_review: bool
    next_recommended_action: str


class ApprovalQueueResponse(SQLModel):
    total_count: int
    items: list[ApprovalQueueItem]
