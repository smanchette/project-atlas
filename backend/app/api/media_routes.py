from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.models import Business, City, County, ImageMetadata, Service
from app.schemas.entities import ImageMetadataRead
from app.services.media_uploads import remove_stored_media_files, store_uploaded_image

router = APIRouter(prefix="/media", tags=["media library"])

ALLOWED_IMAGE_ROLES = {"hero", "service", "support"}


@router.post("/upload", response_model=ImageMetadataRead, status_code=201)
async def upload_media(
    file: UploadFile = File(...),
    business_id: int = Form(...),
    service_id: int | None = Form(default=None),
    city_id: int | None = Form(default=None),
    county_id: int | None = Form(default=None),
    image_title: str | None = Form(default=None),
    image_role: str = Form(default="support"),
    notes: str | None = Form(default=None),
    session: Session = Depends(get_session),
) -> ImageMetadata:
    role = image_role.strip().lower()
    if role not in ALLOWED_IMAGE_ROLES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_ROLES))
        raise HTTPException(status_code=422, detail=f"Image role must be one of: {allowed}")
    _validate_metadata_references(session, business_id, service_id, city_id, county_id)

    settings = get_settings()
    stored = await store_uploaded_image(file, settings)
    metadata = ImageMetadata(
        business_id=business_id,
        service_id=service_id,
        city_id=city_id,
        county_id=county_id,
        file_name=stored.stored_filename,
        original_filename=stored.original_filename,
        stored_filename=stored.stored_filename,
        image_title=_clean_optional(image_title) or _title_from_filename(stored.original_filename),
        asset_url=stored.asset_url,
        optimized_url=stored.optimized_url,
        thumbnail_url=stored.thumbnail_url,
        image_role=role,
        review_status="pending_review",
        notes=_clean_optional(notes),
        exif_status="optimized_copy_stripped",
    )
    try:
        session.add(metadata)
        session.commit()
        session.refresh(metadata)
    except Exception:
        session.rollback()
        remove_stored_media_files(stored, settings)
        raise
    return metadata


def _validate_metadata_references(
    session: Session,
    business_id: int,
    service_id: int | None,
    city_id: int | None,
    county_id: int | None,
) -> None:
    business = session.get(Business, business_id)
    if not business:
        raise HTTPException(status_code=422, detail="Business not found")
    if service_id is not None:
        service = session.get(Service, service_id)
        if not service or service.business_id != business_id:
            raise HTTPException(status_code=422, detail="Service does not belong to the selected business")
    if county_id is not None and not session.get(County, county_id):
        raise HTTPException(status_code=422, detail="County not found")
    if city_id is not None:
        city = session.get(City, city_id)
        if not city:
            raise HTTPException(status_code=422, detail="City not found")
        if county_id is not None and city.county_id != county_id:
            raise HTTPException(status_code=422, detail="City does not belong to the selected county")


def _title_from_filename(filename: str) -> str:
    return " ".join(part.capitalize() for part in filename.rsplit(".", 1)[0].replace("_", "-").split("-") if part)


def _clean_optional(value: str | None) -> str | None:
    cleaned = value.strip() if value else ""
    return cleaned or None
