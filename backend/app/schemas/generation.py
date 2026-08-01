from typing import Any

from sqlmodel import Field, SQLModel


class FAQItem(SQLModel):
    question: str
    answer: str


class DraftContent(SQLModel):
    title: str
    meta_title: str
    meta_description: str
    h1: str
    intro: str
    why_it_matters: str
    signs_section: str
    process_section: str
    prep_section: str
    realtor_property_manager_section: str
    faq_items: list[FAQItem]
    call_to_action: str
    internal_notes: str
    status: str = "draft"


class GenerateDraftRequest(SQLModel):
    allow_overwrite: bool = False
    website_id: int | None = None


class BatchGenerationRequest(SQLModel):
    website_id: int | None = None
    county_ids: list[int] = Field(default_factory=list)
    city_ids: list[int] = Field(default_factory=list)
    status: str | None = None
    confirm: bool = False


class BatchCandidate(SQLModel):
    page_id: int
    page_title: str
    city_name: str
    county_name: str
    page_status: str
    generation_status: str
    eligible: bool
    reason: str | None = None
    planned_page_id: int | None = None
    eligibility_status: str | None = None


class BatchPreviewResponse(SQLModel):
    matched_count: int
    eligible_count: int
    skipped_count: int
    candidates: list[BatchCandidate]
    source_snapshot: dict[str, Any] = Field(default_factory=dict)
    blocked_by_reason: dict[str, int] = Field(default_factory=dict)
    inventory_summary: dict[str, int] = Field(default_factory=dict)


class BatchGenerationResponse(SQLModel):
    generated_count: int
    skipped_count: int
    page_ids: list[int]


class GeneratedDraftResponse(SQLModel):
    page_id: int
    generation_status: str
    status: str
    draft_content: dict[str, Any]
