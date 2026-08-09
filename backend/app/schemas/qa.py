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
    qa_result_id: int | None = None
    page_id: int
    website_id: int | None = None
    site_plan_id: int | None = None
    planned_page_id: int | None = None
    latest_generated_page_revision_id: int | None = None
    content_hash: str
    source_hash: str
    page_composition_id: int | None = None
    composition_version: int | None = None
    composition_source_hash: str | None = None
    qa_algorithm_key: str
    qa_algorithm_version: str
    qa_ruleset_key: str
    qa_ruleset_version: str
    qa_ruleset_hash: str
    readiness_status: Literal["ready", "needs_review", "blocked"]
    checked_at: datetime
    passed_count: int
    warning_count: int
    failed_count: int
    checks: list[QACheckItem]
    result_hash: str
    lifecycle_status: Literal[
        "candidate", "current", "superseded", "historical_unbound"
    ] = "candidate"
    currentness_status: str = "candidate_not_persisted"
    currentness_reasons: list[str] = Field(default_factory=list)
    persisted: bool = False


class QABatchRequest(SQLModel):
    website_id: int | None = None
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
    website_id: int | None = None


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
