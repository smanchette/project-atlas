from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


RequirementState = Literal["required", "advisory", "excluded", "deferred"]


class PageMediaPlanningRecordRead(BaseModel):
    id: int
    website_id: int
    business_id: int
    site_plan_id: int
    version: int
    algorithm_version: str
    generated_media_suggestions: list[dict[str, Any]]
    source_snapshot: dict[str, Any]
    source_hash: str
    generated_at: datetime
    replaces_record_id: int | None
    created_at: datetime
    updated_at: datetime


class PlannedPageMediaRequirementRead(BaseModel):
    id: int
    website_id: int
    business_id: int
    site_plan_id: int
    planned_page_id: int
    planning_record_id: int | None
    component_or_section: str
    placement_key: str
    contract_version: int
    version: int
    requirement_state: RequirementState
    purpose: str
    customer_outcome: str
    intended_subject: str
    orientation: str
    aspect_ratio: str
    minimum_width: int
    minimum_height: int
    crop_intent: str
    focal_point_intent: str
    responsive_behavior: str
    accessibility_intent: str
    caption_intent: str | None
    approved_source_constraints: list[str]
    permitted_reuse_policy: str
    replacement_policy: str
    compatible_page_types: list[str]
    source_suggestion_key: str | None
    decided_by: str
    rationale: str
    decided_at: datetime
    lifecycle_status: str
    replaces_requirement_id: int | None
    created_at: datetime
    updated_at: datetime


class PageMediaPlacementDecisionRequest(BaseModel):
    website_id: int
    site_plan_id: int
    planned_page_id: int
    placement_key: str = Field(min_length=1, max_length=120)
    requirement_state: RequirementState
    decided_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)
    expected_planning_version: int = Field(ge=1)
    source_suggestion_key: str | None = Field(default=None, max_length=240)
    component_or_section: str | None = Field(default=None, max_length=120)
    purpose: str | None = Field(default=None, max_length=1000)
    customer_outcome: str | None = Field(default=None, max_length=1000)
    intended_subject: str | None = Field(default=None, max_length=1000)
    orientation: str | None = Field(default=None, max_length=32)
    aspect_ratio: str | None = Field(default=None, max_length=32)
    minimum_width: int | None = Field(default=None, ge=1)
    minimum_height: int | None = Field(default=None, ge=1)
    crop_intent: str | None = Field(default=None, max_length=500)
    focal_point_intent: str | None = Field(default=None, max_length=500)
    responsive_behavior: str | None = Field(default=None, max_length=1000)
    accessibility_intent: str | None = Field(default=None, max_length=1000)
    caption_intent: str | None = Field(default=None, max_length=1000)
    approved_source_constraints: list[str] | None = None
    permitted_reuse_policy: str | None = Field(default=None, max_length=500)
    replacement_policy: str | None = Field(default=None, max_length=500)
    compatible_page_types: list[str] | None = None


class PageMediaAssetRead(BaseModel):
    id: int
    business_id: int
    website_id: int | None
    media_key: str | None
    media_version: int | None
    image_title: str | None
    original_filename: str | None
    stored_filename: str | None
    managed_storage_path: str | None
    asset_url: str | None
    optimized_url: str | None
    thumbnail_url: str | None
    mime_type: str | None
    file_size: int | None
    width: int | None
    height: int | None
    checksum_sha256: str | None
    acquisition_source: str | None
    creator_source_identity: str | None
    provenance_type: str | None
    provenance_notes: str | None
    rights_status: str | None
    rights_holder: str | None
    rights_notes: str | None
    approved_usage: list[str]
    prohibited_usage: list[str]
    permitted_placement_keys: list[str]
    accessibility_intent: str | None
    reviewed_alt_text: str | None
    governance_status: str
    approval_version: int | None
    approved_by: str | None
    approved_at: datetime | None
    retired_by: str | None
    retirement_rationale: str | None
    retired_at: datetime | None
    replaces_image_metadata_id: int | None
    gps_metadata_status: str
    gps_metadata: dict[str, Any]
    gps_authorized_by: str | None
    gps_authorized_at: datetime | None
    gps_authorization_notes: str | None
    created_at: datetime
    updated_at: datetime


class PageMediaAssetApprovalRequest(BaseModel):
    website_id: int
    business_id: int
    approved_by: str = Field(min_length=1, max_length=160)
    expected_media_version: int = Field(ge=1)


class PageMediaAssetRetirementRequest(BaseModel):
    website_id: int
    business_id: int
    retired_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)
    expected_media_version: int = Field(ge=1)


class PageMediaAssignmentRequest(BaseModel):
    image_metadata_id: int
    assigned_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=2000)
    expected_requirement_version: int = Field(ge=1)
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = Field(default=None, max_length=1000)
    display_preset: str | None = Field(default=None, max_length=80)


class PageMediaAssignmentRead(BaseModel):
    id: int
    generated_page_id: int
    image_metadata_id: int
    website_id: int | None
    site_plan_id: int | None
    planned_page_id: int | None
    media_requirement_id: int | None
    assignment_version: int | None
    media_version: int | None
    placement_contract_version: int | None
    image_role: str
    sort_order: int
    override_focal_x: float | None
    override_focal_y: float | None
    override_alt_text: str | None
    display_preset: str
    status: str
    assigned_by: str | None
    assignment_rationale: str | None
    assigned_at: datetime | None
    replaced_by: str | None
    replacement_rationale: str | None
    replaced_at: datetime | None
    retired_by: str | None
    retirement_rationale: str | None
    retired_at: datetime | None
    replaces_page_image_assignment_id: int | None
    created_at: datetime
    updated_at: datetime


class PageMediaDiagnostic(BaseModel):
    category: str
    status: str
    message: str
    planned_page_id: int | None = None
    placement_key: str | None = None
    record_id: int | None = None


class PageMediaPlannedPageIdentity(BaseModel):
    id: int
    website_id: int
    site_plan_id: int
    generated_page_id: int | None
    page_type: str
    working_name: str
    intended_slug: str


class PageMediaPlacementWorkspace(BaseModel):
    placement_id: int | None
    planned_page: PageMediaPlannedPageIdentity
    suggestion: dict[str, Any] | None
    effective_requirement: PlannedPageMediaRequirementRead | None
    requirement_history: list[PlannedPageMediaRequirementRead]
    active_assignment: PageMediaAssignmentRead | None
    legacy_assignments: list[PageMediaAssignmentRead]
    compatible_asset_ids: list[int]
    blocking_reasons: list[str]
    composition_status: str
    readiness: str


class PageMediaPlanningSummary(BaseModel):
    planned_pages: int
    pages_with_current_plan: int
    pages_without_plan: int
    suggested_placements: int
    required_placements: int
    advisory_placements: int
    excluded_placements: int
    deferred_placements: int
    approved_assignments: int
    missing_required_media: int
    incomplete_governance: int
    incompatible_assignments: int
    stale_compositions: int
    pages_media_ready: int
    page_type_coverage: dict[str, dict[str, int]]


class PageMediaWorkspace(BaseModel):
    website_id: int
    business_id: int
    site_plan_id: int
    site_plan_version: int
    planning_record: PageMediaPlanningRecordRead | None
    placements: list[PageMediaPlacementWorkspace]
    assets: list[PageMediaAssetRead]
    diagnostics: list[PageMediaDiagnostic]
    summary: PageMediaPlanningSummary
    ready: bool
    evaluated_at: datetime
