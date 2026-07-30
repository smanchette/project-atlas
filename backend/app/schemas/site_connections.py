from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import SQLModel


NavigationSetType = Literal["primary", "utility", "footer"]
NavigationRecordStatus = Literal["draft", "active", "disabled"]
InternalLinkApprovalState = Literal["proposed", "approved", "rejected"]
ConnectionDiagnosticStatus = Literal["ready", "needs_attention"]


class NavigationSetRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    set_type: NavigationSetType
    label: str
    status: NavigationRecordStatus
    version: int
    created_at: datetime
    updated_at: datetime


class NavigationItemCreate(SQLModel):
    website_id: int
    site_plan_id: int
    navigation_set_id: int
    target_planned_page_id: int
    parent_navigation_item_id: int | None = None
    label: str
    position: int = Field(default=0, ge=0)
    status: NavigationRecordStatus = "active"


class NavigationItemUpdate(SQLModel):
    parent_navigation_item_id: int | None = None
    label: str | None = None
    position: int | None = Field(default=None, ge=0)
    status: NavigationRecordStatus | None = None


class NavigationItemRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    navigation_set_id: int
    target_planned_page_id: int
    parent_navigation_item_id: int | None = None
    label: str
    position: int
    status: NavigationRecordStatus
    created_at: datetime
    updated_at: datetime


class InternalLinkIntentCreate(SQLModel):
    website_id: int
    site_plan_id: int
    source_planned_page_id: int
    target_planned_page_id: int
    purpose: str
    relationship_type: str
    anchor_guidance: str | None = None
    approval_state: InternalLinkApprovalState = "proposed"


class InternalLinkIntentUpdate(SQLModel):
    purpose: str | None = None
    relationship_type: str | None = None
    anchor_guidance: str | None = None
    approval_state: InternalLinkApprovalState | None = None


class InternalLinkIntentRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    source_planned_page_id: int
    target_planned_page_id: int
    purpose: str
    relationship_type: str
    anchor_guidance: str | None = None
    approval_state: InternalLinkApprovalState
    created_at: datetime
    updated_at: datetime


class SiteConnectionPlanningRecordRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    generated_navigation_suggestions: list[dict[str, Any]]
    generated_internal_link_suggestions: list[dict[str, Any]]
    source_snapshot: dict[str, Any]
    generated_at: datetime
    updated_at: datetime


class SiteConnectionDiagnostic(SQLModel):
    key: str
    label: str
    status: ConnectionDiagnosticStatus
    message: str
    affected_planned_page_ids: list[int] = Field(default_factory=list)
    affected_record_ids: list[int] = Field(default_factory=list)


class SiteConnectionPlanRead(SQLModel):
    website_id: int
    site_plan_id: int
    navigation_sets: list[NavigationSetRead]
    navigation_items: list[NavigationItemRead]
    internal_link_intents: list[InternalLinkIntentRead]
    planning_record: SiteConnectionPlanningRecordRead
    diagnostics: list[SiteConnectionDiagnostic]
    ready: bool
