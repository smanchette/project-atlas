from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import SQLModel


PageType = Literal[
    "home",
    "about",
    "contact",
    "service",
    "county",
    "city",
    "city_service",
    "informational",
    "faq",
]
DraftReadinessStatus = Literal["ready", "blocked", "unsupported"]
WebsiteReadinessItemStatus = Literal[
    "ready",
    "needs_attention",
    "not_assessed",
    "deferred",
]


class SitePlanCreate(SQLModel):
    website_id: int
    plan_key: str = "primary"
    plan_name: str
    status: str = "draft"


class SitePlanUpdate(SQLModel):
    plan_name: str | None = None
    status: str | None = None
    version: int | None = Field(default=None, ge=1)


class SitePlanRead(SQLModel):
    id: int
    website_id: int
    plan_key: str
    plan_name: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime


class PlanningRecordRead(SQLModel):
    id: int
    planned_page_id: int
    generated_answers: dict[str, Any]
    operator_overrides: dict[str, Any]
    effective_answers: dict[str, Any]
    source_snapshot: dict[str, Any]
    confidence_score: float
    confidence_level: str
    missing_information: list[str]
    improvement_recommendations: list[str]
    generated_at: datetime
    reviewed_at: datetime | None = None
    updated_at: datetime


class PlanningRecordOverrideUpdate(SQLModel):
    operator_overrides: dict[str, Any] = Field(default_factory=dict)


class DraftReadinessRead(SQLModel):
    status: DraftReadinessStatus
    page_type_supported: bool
    required_information: list[dict[str, Any]] = Field(default_factory=list)
    blocking_reasons: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class DraftSection(SQLModel):
    key: str
    heading: str
    body: str


class PlannedPageDraftContent(SQLModel):
    schema_version: str = "planned-page-draft-v1"
    page_type: PageType
    title: str
    meta_title: str
    meta_description: str
    h1: str
    intro: str
    sections: list[DraftSection] = Field(default_factory=list)
    faq_items: list[dict[str, str]] = Field(default_factory=list)
    call_to_action: str
    internal_notes: str
    planning_record_id: int
    planning_generated_at: datetime
    operator_override_keys: list[str] = Field(default_factory=list)
    status: str = "draft"


class PlannedPageDraftRequest(SQLModel):
    website_id: int
    allow_overwrite: bool = False


class PlannedPageDraftResponse(SQLModel):
    planned_page_id: int
    generated_page_id: int
    generation_status: str
    planning_status: str
    readiness: DraftReadinessRead
    draft_content: PlannedPageDraftContent


class PlannedPageCreate(SQLModel):
    website_id: int
    site_plan_id: int
    page_type: PageType
    working_name: str
    intended_slug: str
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    parent_planned_page_id: int | None = None
    planning_status: str = "planned"
    generated_page_id: int | None = None


class PlannedPageUpdate(SQLModel):
    page_type: PageType | None = None
    working_name: str | None = None
    intended_slug: str | None = None
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    parent_planned_page_id: int | None = None
    planning_status: str | None = None
    generated_page_id: int | None = None


class PlannedPageRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    page_type: PageType
    working_name: str
    intended_slug: str
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    parent_planned_page_id: int | None = None
    planning_status: str
    generated_page_id: int | None = None
    generated_page_status: str | None = None
    generated_draft: dict[str, Any] | None = None
    draft_readiness: DraftReadinessRead
    planning_record: PlanningRecordRead
    created_at: datetime
    updated_at: datetime


class SitePlanDetail(SitePlanRead):
    planned_pages: list[PlannedPageRead]


class WebsiteReadinessItem(SQLModel):
    key: str
    label: str
    status: WebsiteReadinessItemStatus
    message: str
    affected_planned_page_ids: list[int] = Field(default_factory=list)


class WebsiteReadinessCategory(SQLModel):
    key: Literal[
        "business_readiness",
        "content_readiness",
        "website_readiness",
        "future_readiness",
    ]
    label: str
    status: WebsiteReadinessItemStatus
    items: list[WebsiteReadinessItem] = Field(default_factory=list)


class WebsiteReadinessReport(SQLModel):
    website_id: int
    site_plan_id: int
    site_plan_version: int
    review_ready: bool
    evaluated_at: datetime
    categories: list[WebsiteReadinessCategory]
