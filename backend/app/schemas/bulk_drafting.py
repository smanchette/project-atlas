from datetime import datetime
from typing import Literal

from sqlmodel import Field, SQLModel


BatchRunStatus = Literal[
    "preparing",
    "running",
    "interrupted",
    "completed",
    "completed_with_errors",
]
BatchItemOutcome = Literal[
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
]


class WebsiteDraftGenerationRequest(SQLModel):
    website_id: int
    draft_limit: int | None = Field(default=None, ge=1, le=10_000)


class WebsiteDraftGenerationCounts(SQLModel):
    expected: int = 0
    eligible: int = 0
    generated: int = 0
    already_drafted: int = 0
    skipped: int = 0
    blocked: int = 0
    deferred: int = 0
    excluded: int = 0
    stale: int = 0
    consolidation_recommended: int = 0
    unsupported: int = 0
    errors: int = 0


class WebsiteDraftGenerationItemRead(SQLModel):
    id: int
    inventory_key: str
    ordinal: int
    planned_page_id: int | None
    generated_page_id: int | None
    page_type: str
    working_name: str
    manifest_classification: str
    outcome: BatchItemOutcome
    reasons: list[str] = Field(default_factory=list)
    attempt_count: int
    generated_content_hash: str | None
    started_at: datetime | None
    completed_at: datetime | None


class WebsiteDraftGenerationRunRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    manifest_hash: str
    eligibility_algorithm_version: str
    status: BatchRunStatus
    counts: WebsiteDraftGenerationCounts
    processed_count: int
    progress_total: int
    progress_message: str
    started_at: datetime
    last_resumed_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    items: list[WebsiteDraftGenerationItemRead] = Field(default_factory=list)

