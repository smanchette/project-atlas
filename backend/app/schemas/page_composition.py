from datetime import datetime
from typing import Any, Literal

from pydantic import Field
from sqlmodel import SQLModel


class SemanticComponentDefinitionRead(SQLModel):
    id: int
    component_key: str
    contract_version: int
    purpose: str
    required_inputs: list[str]
    customer_outcome: str
    compatible_page_types: list[str]
    supported_variants: list[str]
    accessibility_requirements: list[str]
    status: str


class PageComponentInstance(SQLModel):
    instance_key: str
    component_key: str
    contract_version: int = 1
    region: str
    position: int
    variant: str = "default"
    input_bindings: dict[str, Any] = Field(default_factory=dict)
    resolved_data: dict[str, Any] = Field(default_factory=dict)


class PageCompositionDecision(SQLModel):
    instance_key: str
    action: Literal["suppress", "configure"]
    variant: str | None = None
    position: int | None = Field(default=None, ge=0)
    rationale: str | None = None


class PageCompositionDecisionUpdate(SQLModel):
    decisions: list[PageCompositionDecision] = Field(default_factory=list)
    decided_by: str = Field(min_length=1)


class PageCompositionRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    planned_page_id: int
    generated_page_id: int
    composition_version: int
    generated_components: list[dict[str, Any]]
    operator_decisions: list[dict[str, Any]]
    effective_components: list[PageComponentInstance]
    source_snapshot: dict[str, Any]
    source_hash: str
    resolved_theme: dict[str, Any] = Field(default_factory=dict)
    status: str
    validation_errors: list[str] = Field(default_factory=list)
    generated_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None


class SitePlanCompositionRefreshResult(SQLModel):
    website_id: int
    site_plan_id: int
    created: int
    refreshed: int
    unchanged: int
    blocked: list[dict[str, Any]] = Field(default_factory=list)
    compositions: list[PageCompositionRead] = Field(default_factory=list)
