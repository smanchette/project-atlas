from datetime import datetime

from sqlmodel import Field, SQLModel

from app.schemas.entities import GeneratedPageRead
from app.schemas.qa import PageQAResult


class ManualFAQItem(SQLModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ManualDraftFields(SQLModel):
    hero_headline: str = Field(min_length=1)
    hero_subheadline: str = Field(min_length=1)
    intro: str = Field(min_length=1)
    service_explanation: str = Field(min_length=1)
    local_city_section: str = Field(min_length=1)
    process_section: str = Field(min_length=1)
    prep_reentry_section: str = Field(min_length=1)
    why_choose_section: str = Field(min_length=1)
    faq_items: list[ManualFAQItem] = Field(min_length=1)
    call_to_action: str = Field(min_length=1)


class ManualDraftSaveRequest(SQLModel):
    draft: ManualDraftFields
    created_by: str | None = None
    reason: str | None = None


class GeneratedPageRevisionRead(SQLModel):
    id: int
    generated_page_id: int
    created_at: datetime
    created_by: str | None = None
    reason: str | None = None
    draft_hash_before: str
    draft_hash_after: str
    draft_content_before: dict
    draft_content_after: dict
    changed_fields: list[str]


class ManualDraftSaveResponse(SQLModel):
    page: GeneratedPageRead
    revision: GeneratedPageRevisionRead
    qa_result: PageQAResult | None = None


class ApprovedPageRepairFields(SQLModel):
    intro: str | None = None
    why_it_matters: str | None = None
    realtor_property_manager_section: str | None = None
    faq_items: list[ManualFAQItem] | None = None
    internal_notes: str | None = None


class ApprovedPageRepairRequest(SQLModel):
    draft: ApprovedPageRepairFields
    repaired_by: str | None = None
    reason: str | None = None


class ApprovedPageRepairResponse(SQLModel):
    page: GeneratedPageRead
    revision: GeneratedPageRevisionRead
    qa_result: PageQAResult
    export_ready: bool
    export_blocker_count: int
    export_warning_count: int
    export_warnings: list[dict[str, str]]
    draft_hash_before: str
    draft_hash_after: str
    payload_hash_before: str
    payload_hash_after: str
    wordpress_post_id: int
    wordpress_status: str | None = None
    wordpress_url: str | None = None
