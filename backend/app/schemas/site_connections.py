from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import SQLModel


NavigationSetType = Literal["primary", "utility", "footer"]
NavigationRecordStatus = Literal["draft", "active", "disabled"]
InternalLinkApprovalState = Literal["proposed", "approved", "rejected"]
ConnectionDiagnosticStatus = Literal["ready", "needs_attention"]


class DecisionProvenanceInput(SQLModel):
    decided_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)
    source_suggestion_key: str | None = Field(default=None, max_length=200)


class NavigationSetRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    set_type: NavigationSetType
    label: str
    status: NavigationRecordStatus
    version: int
    decided_by: str | None = None
    rationale: str | None = None
    decision_version: int | None = None
    decided_at: datetime | None = None
    source_suggestion_key: str | None = None
    created_at: datetime
    updated_at: datetime


class NavigationSetDecisionUpdate(SQLModel):
    status: NavigationRecordStatus
    decided_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)


class NavigationItemCreate(DecisionProvenanceInput):
    website_id: int
    site_plan_id: int
    navigation_set_id: int
    target_planned_page_id: int
    parent_navigation_item_id: int | None = None
    label: str
    position: int = Field(default=0, ge=0)
    status: NavigationRecordStatus = "active"


class NavigationItemUpdate(DecisionProvenanceInput):
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
    decided_by: str | None = None
    rationale: str | None = None
    decision_version: int | None = None
    decided_at: datetime | None = None
    source_suggestion_key: str | None = None
    created_at: datetime
    updated_at: datetime


class InternalLinkIntentCreate(DecisionProvenanceInput):
    website_id: int
    site_plan_id: int
    source_planned_page_id: int
    target_planned_page_id: int
    purpose: str
    relationship_type: str
    anchor_guidance: str | None = None
    approval_state: InternalLinkApprovalState = "proposed"


class InternalLinkIntentUpdate(DecisionProvenanceInput):
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
    decided_by: str | None = None
    rationale: str | None = None
    decision_version: int | None = None
    decided_at: datetime | None = None
    source_suggestion_key: str | None = None
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
