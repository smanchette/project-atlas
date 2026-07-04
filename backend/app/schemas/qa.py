from datetime import datetime
from typing import Any, Literal

from sqlmodel import Field, SQLModel


class QACheckItem(SQLModel):
    key: str
    label: str
    status: Literal["pass", "fail", "warning"]
    severity: Literal["blocker", "warning"]
    message: str
    suggested_fix: str = ""
    issue_location: Literal[
        "content",
        "business_info",
        "city_county_info",
        "media",
        "preview",
        "safety_wording",
    ] = "content"


class PageQAResult(SQLModel):
    page_id: int
    readiness_status: Literal["ready", "needs_review", "blocked"]
    checked_at: datetime
    passed_count: int
    warning_count: int
    failed_count: int
    checks: list[QACheckItem]
    persisted: bool = False


class QABatchRequest(SQLModel):
    page_ids: list[int] = Field(default_factory=list)
    county_ids: list[int] = Field(default_factory=list)
    city_ids: list[int] = Field(default_factory=list)
    page_status: str | None = None
    confirm: bool = False


class QABatchCandidate(SQLModel):
    page_id: int
    page_title: str
    city_name: str
    readiness_status: Literal["ready", "needs_review", "blocked"]
    passed_count: int
    warning_count: int
    failed_count: int


class QABatchResponse(SQLModel):
    matched_count: int
    ready_count: int
    needs_review_count: int
    blocked_count: int
    saved_count: int = 0
    candidates: list[QABatchCandidate]


class PageReviewUpdate(SQLModel):
    internal_notes: str | None = None
    last_reviewed_by: str | None = None


class ApprovalRequest(SQLModel):
    approved_by: str | None = None


class ApprovalAuditRead(SQLModel):
    id: int
    generated_page_id: int
    approved_at: datetime
    approved_by: str | None = None
    qa_status_at_approval: str
    qa_checked_at: datetime
    qa_result_snapshot: dict[str, Any]
    draft_hash_at_approval: str
    page_status_before: str
    page_status_after: str


class ApprovalHistorySummary(SQLModel):
    generated_page_id: int
    approval_count: int
