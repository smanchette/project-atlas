from typing import Any, Literal

from sqlmodel import Field, SQLModel


class ExportWarning(SQLModel):
    code: str
    severity: Literal["warning", "blocker"]
    message: str


class ExportSEO(SQLModel):
    meta_title: str
    meta_description: str
    social_title: str
    social_description: str
    suggested_url_slug: str


class ExportMediaReference(SQLModel):
    image_id: int
    image_role: str
    sort_order: int
    image_title: str | None = None
    alt_text: str
    asset_url: str | None = None
    optimized_url: str | None = None
    thumbnail_url: str | None = None
    display_preset: str
    focal_x: float
    focal_y: float
    review_status: str


class PageExportPackage(SQLModel):
    format_version: str = "1.0"
    page_id: int
    page_status: str
    qa_status: str
    page_title: str
    url_slug: str
    h1: str
    seo: ExportSEO
    content_sections: dict[str, str]
    faq_items: list[dict[str, str]]
    cta_block: str
    city: str
    county: str
    state: str
    service: str
    business_name: str
    phone: str | None = None
    website: str | None = None
    email: str | None = None
    license_number: str | None = None
    certified_operator: str | None = None
    assigned_media: list[ExportMediaReference]
    json_ld: dict[str, Any]
    canonical_url_preview: str
    slug_conflicts: list[int]
    export_ready: bool
    warnings: list[ExportWarning]


class BulkExportRequest(SQLModel):
    page_ids: list[int] = Field(min_length=1)


class BulkExportCandidate(SQLModel):
    page_id: int
    page_title: str
    url_slug: str
    export_ready: bool
    warning_count: int
    blocker_count: int


class BulkExportPreview(SQLModel):
    selected_count: int
    export_ready_count: int
    warning_count: int
    blocker_count: int
    candidates: list[BulkExportCandidate]
