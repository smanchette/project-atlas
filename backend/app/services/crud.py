from datetime import UTC, datetime
from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlmodel import Session, SQLModel, select

ModelT = TypeVar("ModelT", bound=SQLModel)


def list_records(session: Session, model: type[ModelT], offset: int = 0, limit: int = 100) -> list[ModelT]:
    return list(session.exec(select(model).offset(offset).limit(limit)).all())


def get_record(session: Session, model: type[ModelT], record_id: int) -> ModelT:
    record = session.get(model, record_id)
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{model.__name__} not found")
    return record


def create_record(session: Session, model: type[ModelT], payload: SQLModel) -> ModelT:
    _validate_relationships(session, model, payload.model_dump())
    record = model.model_validate(payload)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_record(session: Session, model: type[ModelT], record_id: int, payload: SQLModel) -> ModelT:
    record = get_record(session, model, record_id)
    updates: dict[str, Any] = payload.model_dump(exclude_unset=True)
    _validate_relationships(
        session,
        model,
        {**record.model_dump(), **updates},
        record_id=record_id,
    )
    for key, value in updates.items():
        setattr(record, key, value)
    if hasattr(record, "updated_at"):
        setattr(record, "updated_at", datetime.now(UTC))
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def delete_record(session: Session, model: type[ModelT], record_id: int) -> dict[str, bool]:
    record = get_record(session, model, record_id)
    session.delete(record)
    session.commit()
    return {"ok": True}


def _validate_relationships(
    session: Session,
    model: type[ModelT],
    values: dict[str, Any],
    *,
    record_id: int | None = None,
) -> None:
    from app.models import Brand, Business, City, County, GeneratedPage, Service, Website

    def conflict(message: str) -> None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)

    if model is Brand:
        if not session.get(Business, values.get("business_id")):
            conflict("Brand business does not exist.")
        return

    if model is Website:
        business = session.get(Business, values.get("business_id"))
        if not business:
            conflict("Website business does not exist.")
        brand_id = values.get("brand_id")
        brand = session.get(Brand, brand_id) if brand_id else None
        if brand_id and not brand:
            conflict("Website brand does not exist.")
        if brand and brand.business_id != business.id:
            conflict("Website brand does not belong to the selected business.")
        return

    if model.__name__ == "WebsiteIdentity":
        if not session.get(Website, values.get("website_id")):
            conflict("Website Identity website does not exist.")
        return

    if model is Service:
        if not session.get(Business, values.get("business_id")):
            conflict("Service business does not exist.")
        return

    if model is GeneratedPage:
        business = session.get(Business, values.get("business_id"))
        service = session.get(Service, values.get("service_id"))
        website_id = values.get("website_id")
        website = session.get(Website, website_id) if website_id else None
        if not business or not service:
            conflict("Generated Page requires an existing business and service.")
        if service.business_id != business.id:
            conflict("Generated Page service does not belong to its business.")
        if website_id and not website:
            conflict("Generated Page website does not exist.")
        if website and website.business_id != business.id:
            conflict("Generated Page website does not belong to its business.")
        if website is None:
            active_websites = list(
                session.exec(
                    select(Website).where(
                        Website.business_id == business.id,
                        Website.status == "active",
                    )
                ).all()
            )
            if len(active_websites) > 1:
                conflict("Explicit Website selection is required for a multi-Website business.")
        city = session.get(City, values.get("city_id")) if values.get("city_id") else None
        county = session.get(County, values.get("county_id")) if values.get("county_id") else None
        if values.get("city_id") and not city:
            conflict("Generated Page city does not exist.")
        if values.get("county_id") and not county:
            conflict("Generated Page county does not exist.")
        if city and county and city.county_id != county.id:
            conflict("Generated Page city does not belong to its county.")
        slug = str(values.get("page_slug") or "").strip()
        if website_id and slug:
            statement = select(GeneratedPage).where(
                GeneratedPage.website_id == website_id,
                GeneratedPage.page_slug == slug,
            )
            if record_id is not None:
                statement = statement.where(GeneratedPage.id != record_id)
            if session.exec(statement).first():
                conflict("Generated Page slug already exists for this Website.")

