from datetime import datetime
from typing import Any, Literal

from sqlmodel import Field, SQLModel


EligibilityStatus = Literal[
    "eligible",
    "blocked_missing_required_information",
    "insufficient_local_value",
    "semantic_duplication",
    "consolidation_recommended",
    "deferred",
    "excluded_by_coverage",
    "stale_assessment",
]
DispositionDecision = Literal[
    "accepted", "exception_approved", "deferred", "consolidate"
]


class EligibilityDispositionUpdate(SQLModel):
    decision: DispositionDecision
    rationale: str
    decided_by: str
    accepted_exception: bool = False


class EligibilityDispositionRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    planned_page_id: int
    assessment_id: int
    decision: DispositionDecision
    rationale: str
    decided_by: str
    accepted_exception: bool
    decision_version: int
    decided_at: datetime


class EligibilityAssessmentRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    planned_page_id: int
    status: EligibilityStatus
    algorithm_version: str
    coverage_binding: dict[str, Any]
    expected_inventory_binding: dict[str, Any]
    planning_record_binding: dict[str, Any]
    distinctness_brief_binding: dict[str, Any]
    approved_source_identities: list[dict[str, Any]]
    evidence: dict[str, Any]
    local_value_findings: list[dict[str, Any]]
    semantic_findings: list[dict[str, Any]]
    reasons: list[str]
    assessed_at: datetime
    current: bool
    effective_eligible: bool
    operator_disposition: EligibilityDispositionRead | None = None


class EligibilityManifestCounts(SQLModel):
    expected: int = 0
    assessed: int = 0
    eligible: int = 0
    blocked_missing_required_information: int = 0
    insufficient_local_value: int = 0
    semantic_duplication: int = 0
    consolidation_recommended: int = 0
    deferred: int = 0
    excluded_by_coverage: int = 0
    stale_assessment: int = 0


BatchClassification = Literal[
    "eligible",
    "blocked",
    "excluded",
    "deferred",
    "stale",
    "consolidation_recommended",
]


class PreDraftDistinctnessBriefRead(SQLModel):
    id: int
    website_id: int
    site_plan_id: int
    planned_page_id: int
    algorithm_version: str
    intended_audience: list[str]
    search_intent: str
    approved_fact_identities: list[dict[str, Any]]
    approved_knowledge_identities: list[dict[str, Any]]
    conversion_purpose: str
    required_page_specific_value: list[dict[str, Any]]
    proposed_unique_elements: list[dict[str, Any]]
    related_planned_page_ids: list[int]
    competing_planned_page_ids: list[int]
    source_binding: dict[str, Any]
    brief_hash: str
    generated_at: datetime


class DraftingBatchManifestItem(SQLModel):
    inventory_key: str
    planned_page_id: int | None = None
    page_type: str
    working_name: str
    classification: BatchClassification
    assessment_status: EligibilityStatus | None = None
    current: bool = False
    effective_eligible: bool = False
    reasons: list[str] = Field(default_factory=list)


class DraftingBatchManifestCounts(SQLModel):
    eligible: int = 0
    blocked: int = 0
    excluded: int = 0
    deferred: int = 0
    stale: int = 0
    consolidation_recommended: int = 0


class DraftingBatchManifest(SQLModel):
    website_id: int
    site_plan_id: int
    items: list[DraftingBatchManifestItem] = Field(default_factory=list)
    counts: DraftingBatchManifestCounts
    preview_ready: bool
    blocking_reasons: list[str] = Field(default_factory=list)


class CandidateDraftInput(SQLModel):
    planned_page_id: int
    draft_content: dict[str, Any]
    replacement_approved: bool = False
    replacement_approved_by: str | None = None
    replacement_rationale: str | None = None


class CandidateDraftValidationFinding(SQLModel):
    kind: str
    planned_page_id: int
    target_planned_page_id: int | None = None
    blocking: bool = True
    explanation: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class CandidateDraftValidationResult(SQLModel):
    website_id: int
    site_plan_id: int
    valid: bool
    findings: list[CandidateDraftValidationFinding] = Field(default_factory=list)


class DraftingEligibilityManifest(SQLModel):
    website_id: int
    site_plan_id: int
    algorithm_version: str
    source_snapshot: dict[str, Any]
    counts: EligibilityManifestCounts
    assessments: list[EligibilityAssessmentRead] = Field(default_factory=list)
    distinctness_briefs: list[PreDraftDistinctnessBriefRead] = Field(
        default_factory=list
    )
    inventory_exceptions: list[dict[str, Any]] = Field(default_factory=list)
    batch_preview_ready: bool
    batch_manifest: DraftingBatchManifest
    generated_at: datetime
