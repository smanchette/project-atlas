from typing import TypeVar

from fastapi import APIRouter, Depends
from sqlmodel import Session, SQLModel

from app.db.session import get_session
from app.services.crud import create_record, delete_record, get_record, list_records, update_record

ModelT = TypeVar("ModelT", bound=SQLModel)
CreateT = TypeVar("CreateT", bound=SQLModel)
ReadT = TypeVar("ReadT", bound=SQLModel)
UpdateT = TypeVar("UpdateT", bound=SQLModel)


def build_crud_router(
    *,
    model: type[ModelT],
    create_schema: type[CreateT],
    read_schema: type[ReadT],
    update_schema: type[UpdateT],
    prefix: str,
    tags: list[str],
) -> APIRouter:
    router = APIRouter(prefix=prefix, tags=tags)

    @router.get("", response_model=list[read_schema])  # type: ignore[valid-type]
    def list_items(offset: int = 0, limit: int = 100, session: Session = Depends(get_session)):
        return list_records(session, model, offset, limit)

    @router.post("", response_model=read_schema, status_code=201)  # type: ignore[valid-type]
    def create_item(payload: create_schema, session: Session = Depends(get_session)):  # type: ignore[valid-type]
        return create_record(session, model, payload)

    @router.get("/{record_id}", response_model=read_schema)  # type: ignore[valid-type]
    def get_item(record_id: int, session: Session = Depends(get_session)):
        return get_record(session, model, record_id)

    @router.patch("/{record_id}", response_model=read_schema)  # type: ignore[valid-type]
    def update_item(record_id: int, payload: update_schema, session: Session = Depends(get_session)):  # type: ignore[valid-type]
        return update_record(session, model, record_id, payload)

    @router.delete("/{record_id}")
    def delete_item(record_id: int, session: Session = Depends(get_session)):
        return delete_record(session, model, record_id)

    return router

