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
    WordPressDraftUpdateApplyRequest,
    WordPressDraftUpdateApplyResult,
    WordPressDraftUpdateDryRun,
    WordPressLiveDraftStatus,
    WordPressMediaDryRun,
    WordPressMediaInspectionResult,
    WordPressMediaReconciliationApplyRequest,
    WordPressMediaReconciliationApplyResult,
    WordPressMediaReconciliationDryRun,
    WordPressFeaturedImageApplyRequest,
    WordPressFeaturedImageApplyResult,
    WordPressFeaturedImageDryRun,
    WordPressMediaUploadRequest,
    WordPressMediaUploadResult,
    WordPressManualQualityReviewUpdate,
    WordPressPayloadPreview,
    WordPressPublishDryRun,
    WordPressPublishApplyRequest,
    WordPressPublishApplyResult,
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
from app.services.wordpress_draft_update import (
    apply_wordpress_draft_update,
    dry_run_wordpress_draft_update,
)
from app.services.wordpress_publish import apply_wordpress_publish, dry_run_wordpress_publish
from app.services.wordpress_media_sync import (
    dry_run_wordpress_media,
    dry_run_wordpress_media_reconciliation,
    inspect_wordpress_media,
    reconcile_wordpress_media,
    apply_wordpress_featured_image,
    dry_run_wordpress_featured_image,
    upload_wordpress_media,
)
from app.services.wordpress_quality_review import (
    build_wordpress_draft_quality_review,
    list_wordpress_draft_quality_reviews,
    update_manual_quality_review,
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


@router.patch("/draft-quality-review/{page_id}/manual-review", response_model=WordPressDraftQualityReviewItem)
def update_draft_quality_manual_review(
    page_id: int,
    payload: WordPressManualQualityReviewUpdate,
    session: Session = Depends(get_session),
) -> WordPressDraftQualityReviewItem:
    return update_manual_quality_review(session, page_id, payload)


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


@router.post("/draft-update/dry-run/{page_id}", response_model=WordPressDraftUpdateDryRun)
def draft_update_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressDraftUpdateDryRun:
    return dry_run_wordpress_draft_update(session, page_id)


@router.post("/draft-update/apply/{page_id}", response_model=WordPressDraftUpdateApplyResult)
def draft_update_apply(
    page_id: int,
    payload: WordPressDraftUpdateApplyRequest,
    session: Session = Depends(get_session),
) -> WordPressDraftUpdateApplyResult:
    return apply_wordpress_draft_update(session, page_id, payload)


@router.post("/publish/dry-run/{page_id}", response_model=WordPressPublishDryRun)
def publish_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressPublishDryRun:
    return dry_run_wordpress_publish(session, page_id)


@router.post("/publish/apply/{page_id}", response_model=WordPressPublishApplyResult)
def publish_apply(
    page_id: int,
    payload: WordPressPublishApplyRequest,
    session: Session = Depends(get_session),
) -> WordPressPublishApplyResult:
    return apply_wordpress_publish(session, page_id, payload)


@router.post("/media/dry-run/{page_id}", response_model=WordPressMediaDryRun)
def media_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressMediaDryRun:
    return dry_run_wordpress_media(session, page_id)


@router.post("/media/upload/{page_id}", response_model=WordPressMediaUploadResult)
def media_upload(
    page_id: int,
    payload: WordPressMediaUploadRequest,
    session: Session = Depends(get_session),
) -> WordPressMediaUploadResult:
    return upload_wordpress_media(session, page_id, payload)


@router.get("/media/inspect/{page_id}", response_model=WordPressMediaInspectionResult)
def media_inspect(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressMediaInspectionResult:
    return inspect_wordpress_media(session, page_id)


@router.post("/media/reconciliation/dry-run/{page_id}", response_model=WordPressMediaReconciliationDryRun)
def media_reconciliation_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressMediaReconciliationDryRun:
    return dry_run_wordpress_media_reconciliation(session, page_id)


@router.post("/media/reconciliation/apply/{page_id}", response_model=WordPressMediaReconciliationApplyResult)
def media_reconciliation_apply(
    page_id: int,
    payload: WordPressMediaReconciliationApplyRequest,
    session: Session = Depends(get_session),
) -> WordPressMediaReconciliationApplyResult:
    return reconcile_wordpress_media(session, page_id, payload)


@router.post("/media/featured-image/dry-run/{page_id}", response_model=WordPressFeaturedImageDryRun)
def featured_image_dry_run(
    page_id: int,
    session: Session = Depends(get_session),
) -> WordPressFeaturedImageDryRun:
    return dry_run_wordpress_featured_image(session, page_id)


@router.post("/media/featured-image/apply/{page_id}", response_model=WordPressFeaturedImageApplyResult)
def featured_image_apply(
    page_id: int,
    payload: WordPressFeaturedImageApplyRequest,
    session: Session = Depends(get_session),
) -> WordPressFeaturedImageApplyResult:
    return apply_wordpress_featured_image(session, page_id, payload)
