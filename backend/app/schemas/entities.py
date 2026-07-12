from datetime import datetime
from typing import Any

from pydantic import Field
from sqlmodel import SQLModel


class BusinessBase(SQLModel):
    company_name: str
    brand_name: str | None = None
    business_type: str
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    main_city: str | None = None
    state: str = "FL"
    license_number: str | None = None
    certified_operator: str | None = None
    description: str | None = None


class BusinessCreate(BusinessBase):
    pass


class BusinessUpdate(SQLModel):
    company_name: str | None = None
    brand_name: str | None = None
    business_type: str | None = None
    phone: str | None = None
    email: str | None = None
    website: str | None = None
    main_city: str | None = None
    state: str | None = None
    license_number: str | None = None
    certified_operator: str | None = None
    description: str | None = None


class BusinessRead(BusinessBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ServiceBase(SQLModel):
    business_id: int
    service_name: str
    service_slug: str
    service_category: str | None = None
    short_description: str | None = None
    long_description: str | None = None
    status: str = "active"


class ServiceCreate(ServiceBase):
    pass


class ServiceUpdate(SQLModel):
    business_id: int | None = None
    service_name: str | None = None
    service_slug: str | None = None
    service_category: str | None = None
    short_description: str | None = None
    long_description: str | None = None
    status: str | None = None


class ServiceRead(ServiceBase):
    id: int
    created_at: datetime
    updated_at: datetime


class CountyBase(SQLModel):
    state: str = "FL"
    county_name: str
    status: str = "active"


class CountyCreate(CountyBase):
    pass


class CountyUpdate(SQLModel):
    state: str | None = None
    county_name: str | None = None
    status: str | None = None


class CountyRead(CountyBase):
    id: int


class CityBase(SQLModel):
    county_id: int
    city_name: str
    state: str = "FL"
    city_slug: str
    priority: str = "Medium"
    is_primary_market: bool = False
    notes: str | None = None
    status: str = "active"


class CityCreate(CityBase):
    pass


class CityUpdate(SQLModel):
    county_id: int | None = None
    city_name: str | None = None
    state: str | None = None
    city_slug: str | None = None
    priority: str | None = None
    is_primary_market: bool | None = None
    notes: str | None = None
    status: str | None = None


class CityRead(CityBase):
    id: int


class GeneratedPageBase(SQLModel):
    business_id: int
    service_id: int
    city_id: int | None = None
    county_id: int | None = None
    page_type: str
    page_title: str
    page_slug: str
    meta_title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    content_body: str | None = None
    draft_content: dict[str, Any] | None = None
    generation_status: str = "not_generated"
    generated_at: datetime | None = None
    qa_status: str = "not_run"
    qa_result: dict[str, Any] | None = None
    qa_checked_at: datetime | None = None
    internal_notes: str | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_by: str | None = None
    status: str = "draft"
    wordpress_post_id: int | None = None
    wordpress_url: str | None = None
    wordpress_status: str | None = None
    wordpress_created_at: datetime | None = None
    last_wordpress_sync_at: datetime | None = None


class GeneratedPageCreate(GeneratedPageBase):
    pass


class GeneratedPageUpdate(SQLModel):
    business_id: int | None = None
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    page_type: str | None = None
    page_title: str | None = None
    page_slug: str | None = None
    meta_title: str | None = None
    meta_description: str | None = None
    h1: str | None = None
    content_body: str | None = None
    draft_content: dict[str, Any] | None = None
    generation_status: str | None = None
    generated_at: datetime | None = None
    qa_status: str | None = None
    qa_result: dict[str, Any] | None = None
    qa_checked_at: datetime | None = None
    internal_notes: str | None = None
    last_reviewed_at: datetime | None = None
    last_reviewed_by: str | None = None
    status: str | None = None
    wordpress_post_id: int | None = None
    wordpress_url: str | None = None
    wordpress_status: str | None = None
    wordpress_created_at: datetime | None = None
    last_wordpress_sync_at: datetime | None = None


class GeneratedPageRead(GeneratedPageBase):
    id: int
    created_at: datetime
    updated_at: datetime


class ImageMetadataBase(SQLModel):
    business_id: int
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    file_name: str
    image_title: str | None = None
    alt_text: str | None = None
    reviewed_alt_text: str | None = None
    caption: str | None = None
    asset_url: str | None = None
    thumbnail_url: str | None = None
    optimized_url: str | None = None
    original_filename: str | None = None
    stored_filename: str | None = None
    notes: str | None = None
    focal_x: float = Field(default=0.5, ge=0, le=1)
    focal_y: float = Field(default=0.5, ge=0, le=1)
    image_role: str = "support"
    review_status: str = "pending"
    geo_city: str | None = None
    geo_state: str | None = "FL"
    image_prompt: str | None = None
    exif_status: str = "pending"


class ImageMetadataCreate(ImageMetadataBase):
    pass


class ImageMetadataUpdate(SQLModel):
    business_id: int | None = None
    service_id: int | None = None
    city_id: int | None = None
    county_id: int | None = None
    file_name: str | None = None
    image_title: str | None = None
    alt_text: str | None = None
    reviewed_alt_text: str | None = None
    caption: str | None = None
    asset_url: str | None = None
    thumbnail_url: str | None = None
    optimized_url: str | None = None
    original_filename: str | None = None
    stored_filename: str | None = None
    notes: str | None = None
    focal_x: float = Field(default=0.5, ge=0, le=1)
    focal_y: float = Field(default=0.5, ge=0, le=1)
    image_role: str | None = None
    review_status: str | None = None
    geo_city: str | None = None
    geo_state: str | None = None
    image_prompt: str | None = None
    exif_status: str | None = None


class ImageMetadataRead(ImageMetadataBase):
    id: int
    created_at: datetime
    updated_at: datetime
    wordpress_media_id: int | None = None
    wordpress_media_url: str | None = None
    wordpress_media_status: str | None = None
    wordpress_media_checksum: str | None = None
    wordpress_media_uploaded_at: datetime | None = None
    last_wordpress_media_sync_at: datetime | None = None


class PageImageAssignmentBase(SQLModel):
    generated_page_id: int
    image_metadata_id: int
    image_role: str = "hero"
    sort_order: int = 0
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str = "hero_desktop"
    status: str = "active"


class PageImageAssignmentCreate(PageImageAssignmentBase):
    pass


class PageImageAssignmentUpdate(SQLModel):
    image_metadata_id: int | None = None
    image_role: str | None = None
    sort_order: int | None = None
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str | None = None
    status: str | None = None


class PageImageAssignmentRead(PageImageAssignmentBase):
    id: int
    created_at: datetime
    updated_at: datetime


class KnowledgeBlockBase(SQLModel):
    business_id: int
    service_id: int
    title: str
    slug: str
    question: str
    short_answer: str
    long_answer: str
    category: str
    customer_type: str = "general"
    confidence_level: str = "Medium"
    source_notes: str | None = None
    sort_order: int = 0
    status: str = "active"


class KnowledgeBlockCreate(KnowledgeBlockBase):
    pass


class KnowledgeBlockUpdate(SQLModel):
    business_id: int | None = None
    service_id: int | None = None
    title: str | None = None
    slug: str | None = None
    question: str | None = None
    short_answer: str | None = None
    long_answer: str | None = None
    category: str | None = None
    customer_type: str | None = None
    confidence_level: str | None = None
    source_notes: str | None = None
    sort_order: int | None = None
    status: str | None = None


class KnowledgeBlockRead(KnowledgeBlockBase):
    id: int
    created_at: datetime
    updated_at: datetime


class SettingBase(SQLModel):
    setting_key: str
    setting_value: str | None = None
    description: str | None = None


class SettingCreate(SettingBase):
    pass


class SettingUpdate(SQLModel):
    setting_key: str | None = None
    setting_value: str | None = None
    description: str | None = None


class SettingRead(SettingBase):
    id: int
    created_at: datetime
    updated_at: datetime
