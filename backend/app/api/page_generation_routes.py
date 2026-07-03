from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.generation import (
    BatchGenerationRequest,
    BatchGenerationResponse,
    BatchPreviewResponse,
    GenerateDraftRequest,
    GeneratedDraftResponse,
)
from app.services.draft_generation import (
    DraftGenerationError,
    UnsafeContentError,
    generate_batch,
    generate_page_draft,
    preview_batch,
)

router = APIRouter(prefix="/generated-pages", tags=["page generation"])


@router.post("/{page_id}/generate-draft", response_model=GeneratedDraftResponse)
def generate_single_draft(
    page_id: int,
    payload: GenerateDraftRequest,
    session: Session = Depends(get_session),
) -> GeneratedDraftResponse:
    try:
        page = generate_page_draft(
            session,
            page_id,
            allow_overwrite=payload.allow_overwrite,
        )
    except UnsafeContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DraftGenerationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return GeneratedDraftResponse(
        page_id=page.id or page_id,
        generation_status=page.generation_status,
        status=page.status,
        draft_content=page.draft_content or {},
    )


@router.post("/generate-batch-preview", response_model=BatchPreviewResponse)
def generate_batch_preview(
    payload: BatchGenerationRequest,
    session: Session = Depends(get_session),
) -> BatchPreviewResponse:
    return preview_batch(
        session,
        county_ids=payload.county_ids,
        city_ids=payload.city_ids,
        status=payload.status,
    )


@router.post("/generate-batch", response_model=BatchGenerationResponse)
def generate_confirmed_batch(
    payload: BatchGenerationRequest,
    session: Session = Depends(get_session),
) -> BatchGenerationResponse:
    if not payload.confirm:
        raise HTTPException(status_code=400, detail="Batch generation requires confirm=true after preview.")

    try:
        preview = preview_batch(
            session,
            county_ids=payload.county_ids,
            city_ids=payload.city_ids,
            status=payload.status,
        )
        page_ids = generate_batch(
            session,
            county_ids=payload.county_ids,
            city_ids=payload.city_ids,
            status=payload.status,
        )
    except UnsafeContentError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except DraftGenerationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    return BatchGenerationResponse(
        generated_count=len(page_ids),
        skipped_count=preview.skipped_count,
        page_ids=page_ids,
    )
