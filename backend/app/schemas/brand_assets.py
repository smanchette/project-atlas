from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BrandAssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    business_id: int
    brand_id: int
    asset_key: str
    version: int
    asset_type: str
    variant_key: str
    purpose: str
    approved_usage: list[str]
    restrictions: list[str]
    accessibility_description: str
    original_filename: str
    asset_url: str
    optimized_url: str | None
    thumbnail_url: str | None
    mime_type: str
    file_size: int
    width: int
    height: int
    checksum_sha256: str
    provenance_type: str
    provenance_notes: str | None
    rights_status: str
    rights_holder: str | None
    rights_notes: str | None
    status: str
    created_by: str
    approved_by: str | None
    approved_at: datetime | None
    retired_by: str | None
    retirement_rationale: str | None
    retired_at: datetime | None
    replaces_brand_asset_id: int | None
    created_at: datetime
    updated_at: datetime


class BrandAssetApprovalRequest(BaseModel):
    approved_by: str = Field(min_length=1, max_length=160)


class BrandAssetRetirementRequest(BaseModel):
    retired_by: str = Field(min_length=1, max_length=160)
    rationale: str = Field(min_length=1, max_length=1000)


class IdentityAssetAssignmentCreate(BaseModel):
    brand_asset_id: int
    slot: str
    assigned_by: str = Field(min_length=1, max_length=160)
    rationale: str | None = Field(default=None, max_length=1000)


class IdentityAssetAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    website_identity_id: int
    website_id: int
    brand_id: int
    brand_asset_id: int
    slot: str
    version: int
    status: str
    assigned_by: str
    rationale: str | None
    assigned_at: datetime
    replaced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    asset: BrandAssetRead | None = None


class WebsiteIdentityAssetsRead(BaseModel):
    website_identity_id: int
    website_id: int
    brand_id: int
    active: dict[str, IdentityAssetAssignmentRead]
    history: list[IdentityAssetAssignmentRead]
    missing_slots: list[str]
