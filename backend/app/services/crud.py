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
    record = model.model_validate(payload)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def update_record(session: Session, model: type[ModelT], record_id: int, payload: SQLModel) -> ModelT:
    record = get_record(session, model, record_id)
    updates: dict[str, Any] = payload.model_dump(exclude_unset=True)
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

