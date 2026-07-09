from fastapi import APIRouter, Depends
from sqlmodel import Session

from app.db.session import get_session
from app.schemas.wordpress import (
    WordPressConnectionResult,
    WordPressDraftCreateRequest,
    WordPressDraftCreateResult,
    WordPressDraftDryRun,
    WordPressDraftQualityReviewItem,
    WordPressDraftQualityReviewList,
    WordPressDraftQueueResponse,
    WordPressDraftReviewDetail,
    WordPressDraftReviewList,
    WordPressLiveDraftStatus,
    WordPressPayloadPreview,
    WordPressSettingsRead,
    WordPressSettingsUpdate,
)
from app.services.wordpress_draft_review import (
    check_live_wordpress_draft_status,
    get_wordpress_draft_review,
    list_wordpress_draft_reviews,
)
from app.services.wordpress_draft_queue import build_wordpress_draft_queue
from app.services.wordpress_drafts import create_wordpress_draft, dry_run_wordpress_draft
from app.services.wordpress_quality_review import (
    build_wordpress_draft_quality_review,
    list_wordpress_draft_quality_reviews,
)
from app.services.wordpress_sandbox import (
    build_wordpress_payload_preview,
    read_wordpress_settings,
    save_wordpress_settings,
    test_wordpress_connection,
)

router = APIRouter(prefix="/wordpress", tags=["wordpress sandbox"])


@router.get("/settings", response_model=WordPressSettingsRead)
def get_wordpress_settings(
    session: Session = Depends(get_session),
) -> WordPressSettingsRead:
    return read_wordpress_settings(session)


@router.put("/settings", response_model=WordPressSettingsRead)
def update_wordpress_settings(
    payload: WordPressSettingsUpdate,
    session: Session = Depends(get_session),
) -> WordPressSettingsRead:
    return save_wordpress_settings(session, payload)


@router.post("/test-connection", response_model=WordPressConnectionResult)
def test_connection(
    session: Session = Depends(get_session),
) -> WordPressConnectionResult:
    return test_wordpress_connection(session)


@router.get("/pages/{page_id}/payload-preview", response_model=WordPressPayloadPreview)
def payload_preview(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressPayloadPreview:
    return build_wordpress_payload_preview(session, page_id)


@router.get("/draft-review", response_model=WordPressDraftReviewList)
def draft_review_list(
    session: Session = Depends(get_session),
) -> WordPressDraftReviewList:
    return list_wordpress_draft_reviews(session)


@router.get("/draft-queue", response_model=WordPressDraftQueueResponse)
def draft_queue(
    session: Session = Depends(get_session),
) -> WordPressDraftQueueResponse:
    return build_wordpress_draft_queue(session)


@router.get("/draft-quality-review", response_model=WordPressDraftQualityReviewList)
def draft_quality_review_list(
    session: Session = Depends(get_session),
) -> WordPressDraftQualityReviewList:
    return list_wordpress_draft_quality_reviews(session)


@router.get("/draft-quality-review/{page_id}", response_model=WordPressDraftQualityReviewItem)
def draft_quality_review_detail(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressDraftQualityReviewItem:
    return build_wordpress_draft_quality_review(session, page_id)


@router.get("/draft-review/{page_id}", response_model=WordPressDraftReviewDetail)
def draft_review_detail(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressDraftReviewDetail:
    return get_wordpress_draft_review(session, page_id)


@router.get("/draft-review/{page_id}/live-status", response_model=WordPressLiveDraftStatus)
def draft_review_live_status(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressLiveDraftStatus:
    return check_live_wordpress_draft_status(session, page_id)


@router.post("/draft/dry-run/{page_id}", response_model=WordPressDraftDryRun)
def draft_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressDraftDryRun:
    return dry_run_wordpress_draft(session, page_id)


@router.post("/draft/create/{page_id}", response_model=WordPressDraftCreateResult)
def draft_create(
    page_id: int,
    payload: WordPressDraftCreateRequest,
    session: Session = Depends(get_session),
) -> WordPressDraftCreateResult:
    return create_wordpress_draft(session, page_id, payload)
