from datetime import datetime

from pydantic import Field
from sqlmodel import SQLModel

from app.schemas.entities import ImageMetadataRead


class MediaAssignmentRequest(SQLModel):
    image_metadata_id: int


class MediaAssignmentCreateRequest(SQLModel):
    image_metadata_id: int
    image_role: str
    sort_order: int | None = None
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str | None = None


class MediaAssignmentUpdateRequest(SQLModel):
    sort_order: int | None = None
    override_focal_x: float | None = Field(default=None, ge=0, le=1)
    override_focal_y: float | None = Field(default=None, ge=0, le=1)
    override_alt_text: str | None = None
    display_preset: str | None = None


class MediaAssignmentOrderRequest(SQLModel):
    assignment_ids: list[int]


class AssignedMediaRead(SQLModel):
    assignment_id: int
    generated_page_id: int
    image_role: str
    sort_order: int
    override_focal_x: float | None
    override_focal_y: float | None
    override_alt_text: str | None
    display_preset: str
    effective_focal_x: float
    effective_focal_y: float
    effective_alt_text: str
    status: str
    created_at: datetime
    updated_at: datetime
    image: ImageMetadataRead
