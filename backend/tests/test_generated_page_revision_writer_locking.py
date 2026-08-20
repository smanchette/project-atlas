from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.models import GeneratedPage
from app.schemas.page_editor import (
    ApprovedPageRepairFields,
    ApprovedPageRepairRequest,
    ManualDraftSaveRequest,
)
from app.services.approved_page_repair import repair_approved_page
from app.services.page_editor import save_manual_draft


class _SingleRowResult:
    def __init__(self, row: object) -> None:
        self._row = row

    def one_or_none(self) -> object:
        return self._row


class _CaptureFirstStatementSession:
    def __init__(self, row: object) -> None:
        self._row = row
        self.statements: list[Any] = []

    def exec(self, statement: Any) -> _SingleRowResult:
        self.statements.append(statement)
        if len(self.statements) > 1:
            raise AssertionError("Writer queried mutable state before rejecting the row.")
        return _SingleRowResult(self._row)


def _assert_exact_generated_page_lock(statement: Any, page_id: int) -> None:
    sql = " ".join(
        str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        ).split()
    )
    assert statement.column_descriptions[0]["entity"] is GeneratedPage
    assert f"WHERE generatedpage.id = {page_id}" in sql
    assert sql.endswith("FOR UPDATE")
    assert statement.get_execution_options()["populate_existing"] is True


def test_manual_draft_writer_locks_exact_page_before_state_validation() -> None:
    page_id = 701
    session = _CaptureFirstStatementSession(
        SimpleNamespace(id=page_id, status="approved")
    )

    with pytest.raises(HTTPException) as exc_info:
        save_manual_draft(
            session,  # type: ignore[arg-type]
            page_id,
            ManualDraftSaveRequest(draft={}),
        )

    assert exc_info.value.status_code == 409
    assert len(session.statements) == 1
    _assert_exact_generated_page_lock(session.statements[0], page_id)


def test_approved_repair_writer_locks_exact_page_before_state_validation() -> None:
    page_id = 702
    session = _CaptureFirstStatementSession(
        SimpleNamespace(id=page_id, status="draft")
    )

    with pytest.raises(HTTPException) as exc_info:
        repair_approved_page(
            session,  # type: ignore[arg-type]
            page_id,
            ApprovedPageRepairRequest(draft=ApprovedPageRepairFields()),
        )

    assert exc_info.value.status_code == 409
    assert len(session.statements) == 1
    _assert_exact_generated_page_lock(session.statements[0], page_id)
