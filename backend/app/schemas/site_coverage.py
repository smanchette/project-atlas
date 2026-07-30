from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import SQLModel


CoverageDecisionStatus = Literal["included", "excluded", "deferred"]
CoverageInventoryDisposition = Literal[
    "expected",
    "matching",
    "missing",
    "excluded",
    "deferred",
    "pending_decision",
    "unsupported_extra",
    "unexplained_historical",
    "relationship_conflict",
    "slug_conflict",
]


class CoverageDecisionUpdate(SQLModel):
    status: CoverageDecisionStatus
    rationale: str | None = None
    decided_by: str


class CountyCoverageDecisionUpdate(CoverageDecisionUpdate):
    page_appropriate: bool = False


class ServiceCoverageDecisionRead(SQLModel):
    id: int
    website_id: int
    service_id: int
    status: CoverageDecisionStatus
    rationale: str | None = None
    decided_by: str
    decision_version: int
    decided_at: datetime
    updated_at: datetime


class CountyCoverageDecisionRead(SQLModel):
    id: int
    website_id: int
    county_id: int
    status: CoverageDecisionStatus
    page_appropriate: bool
    rationale: str | None = None
    decided_by: str
    decision_version: int
    decided_at: datetime
    updated_at: datetime


class CityCoverageDecisionRead(SQLModel):
    id: int
    website_id: int
    city_id: int
    status: CoverageDecisionStatus
    rationale: str | None = None
    decided_by: str
    decision_version: int
    decided_at: datetime
    updated_at: datetime


class ServiceCityCoverageDecisionRead(SQLModel):
    id: int
    website_id: int
    service_id: int
    city_id: int
    status: CoverageDecisionStatus
    rationale: str | None = None
    decided_by: str
    decision_version: int
    decided_at: datetime
    updated_at: datetime


class CoveragePlanningRecordRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    generated_service_candidates: list[dict[str, Any]]
    generated_county_candidates: list[dict[str, Any]]
    generated_city_candidates: list[dict[str, Any]]
    generated_matrix_candidates: list[dict[str, Any]]
    source_snapshot: dict[str, Any]
    generated_at: datetime
    updated_at: datetime


class CoveragePolicyRead(SQLModel):
    website_id: int
    site_plan_id: int
    planning_record: CoveragePlanningRecordRead
    service_decisions: list[ServiceCoverageDecisionRead]
    county_decisions: list[CountyCoverageDecisionRead]
    city_decisions: list[CityCoverageDecisionRead]
    matrix_decisions: list[ServiceCityCoverageDecisionRead]


class CoverageInventoryItem(SQLModel):
    inventory_key: str
    page_type: str
    working_name: str
    intended_slug: str
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    disposition: CoverageInventoryDisposition
    planned_page_id: int | None = None
    generated_page_id: int | None = None
    reason: str


class CoverageInventoryCounts(SQLModel):
    expected: int = 0
    planned: int = 0
    missing: int = 0
    excluded: int = 0
    deferred: int = 0
    pending_decision: int = 0
    unsupported_extra: int = 0
    unexplained_historical: int = 0
    relationship_conflict: int = 0
    slug_conflict: int = 0


class CoverageInventoryPreview(SQLModel):
    website_id: int
    site_plan_id: int
    counts: CoverageInventoryCounts
    items: list[CoverageInventoryItem] = Field(default_factory=list)
    reconciliation_ready: bool
    blocking_reasons: list[str] = Field(default_factory=list)


class CoverageReconciliationResult(SQLModel):
    website_id: int
    site_plan_id: int
    created_planned_page_ids: list[int] = Field(default_factory=list)
    created_count: int
    before: CoverageInventoryCounts
    after: CoverageInventoryCounts
    idempotent: bool
