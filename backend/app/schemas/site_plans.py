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
    planning_record: PlanningRecordRead
    created_at: datetime
    updated_at: datetime


class SitePlanDetail(SitePlanRead):
    planned_pages: list[PlannedPageRead]
