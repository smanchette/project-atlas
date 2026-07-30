from datetime import datetime
from typing import Any

from sqlmodel import Field, SQLModel

from app.schemas.entities import GeneratedPageRead
from app.schemas.qa import PageQAResult


class ManualFAQItem(SQLModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class ManualDraftSaveRequest(SQLModel):
    # The service validates this mapping against the Generated Page's single
    # authoritative page-type review contract.
    draft: dict[str, Any]
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
