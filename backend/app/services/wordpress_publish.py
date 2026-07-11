from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import secrets

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import GeneratedPage, GeneratedPageRevision, WordPressDraftAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressDraftRequestPayload,
    WordPressPublishDryRun,
    WordPressPublishRequestPayload,
)
from app.services.page_export import build_page_export_package
from app.services.wordpress_draft_review import check_live_wordpress_draft_status
from app.services.wordpress_drafts import _payload_hash
from app.services.wordpress_quality_review import build_wordpress_draft_quality_review
from app.services.wordpress_sandbox import (
    build_wordpress_payload_preview,
    get_wordpress_application_password,
    read_wordpress_settings,
)

TOKEN_TTL_MINUTES = 15
_publish_confirmation_secret = secrets.token_bytes(32)


def dry_run_wordpress_publish(session: Session, page_id: int) -> WordPressPublishDryRun:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")

    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    export_package = build_page_export_package(session, page_id)
    quality_review = (
        build_wordpress_draft_quality_review(session, page_id)
        if page.wordpress_post_id
        else None
    )
    preview = build_wordpress_payload_preview(session, page_id)
    draft_payload = WordPressDraftRequestPayload(
        title=preview.payload.title,
        slug=preview.payload.slug,
        status="draft",
        content=preview.payload.content,
        excerpt=preview.payload.excerpt,
    )
    publish_payload = WordPressPublishRequestPayload(
        title=preview.payload.title,
        slug=preview.payload.slug,
        status="publish",
        content=preview.payload.content,
        excerpt=preview.payload.excerpt,
    )
    current_payload_hash = _payload_hash(draft_payload)
    publish_payload_hash = _model_hash(publish_payload)
    latest_update = _latest_successful_update_audit(session, page_id)
    latest_revision_at = session.exec(
        select(func.max(GeneratedPageRevision.created_at)).where(
            GeneratedPageRevision.generated_page_id == page_id
        )
    ).one()
    qa_current = bool(
        page.qa_checked_at
        and (
            latest_revision_at is None
            or _timestamp(page.qa_checked_at) >= _timestamp(latest_revision_at)
        )
    )
    blocker_count = sum(warning.severity == "blocker" for warning in export_package.warnings)
    live_status = check_live_wordpress_draft_status(session, page_id) if page.wordpress_post_id else None

    gates = [
        _gate(
            "sandbox_mode",
            "WordPress mode is sandbox",
            settings.publishing_mode == "sandbox",
            "WordPress mode must be Sandbox. Default disabled mode cannot publish.",
        ),
        _gate(
            "credentials_ready",
            "Connection credentials are available",
            bool(settings.site_url and settings.username and password),
            "Site URL, username, and the process-memory application password are required.",
        ),
        _gate(
            "page_approved",
            "Atlas page is approved",
            page.status == "approved",
            f"Atlas page status is {page.status}; explicit approval is required.",
        ),
        _gate(
            "manual_review_ready",
            "Manual review is ready for publish review",
            bool(
                quality_review
                and quality_review.manual_review.review_status == "ready_for_manual_publish_review"
            ),
            "Manual review status must be ready_for_manual_publish_review.",
        ),
        _gate(
            "qa_ready",
            "QA status is ready",
            page.qa_status == "ready" and page.qa_checked_at is not None,
            f"QA status is {page.qa_status}; run QA and resolve all issues.",
        ),
        _gate(
            "qa_current",
            "QA is current after edits",
            qa_current,
            "QA is missing or older than the latest manual revision.",
        ),
        _gate(
            "export_clear",
            "Export package has no blockers",
            blocker_count == 0,
            f"Export package has {blocker_count} blocker warning(s).",
        ),
        _gate(
            "quality_review_no_fails",
            "WP Quality Review has no fails",
            bool(quality_review and quality_review.fail_count == 0),
            f"WP Quality Review has {quality_review.fail_count if quality_review else 'unknown'} fail(s).",
        ),
        _gate(
            "has_wordpress_ref",
            "Existing WordPress draft reference exists",
            page.wordpress_post_id is not None,
            "This Atlas page does not have a saved WordPress draft reference.",
        ),
        _gate(
            "atlas_wordpress_status_draft",
            "Saved Atlas WordPress status is draft",
            page.wordpress_status == "draft",
            f"Saved Atlas WordPress status is {page.wordpress_status or 'missing'}; only draft refs can be published later.",
        ),
        _gate(
            "live_wordpress_get",
            "Live WordPress GET confirms target exists",
            bool(live_status and not live_status.error_message),
            live_status.error_message if live_status and live_status.error_message else "Live WordPress GET could not confirm the saved post.",
        ),
        _gate(
            "live_wordpress_status_draft",
            "Live WordPress status is draft",
            bool(live_status and live_status.wordpress_status == "draft"),
            f"Live WordPress status is {(live_status.wordpress_status if live_status else None) or 'unknown'}; publish dry run requires a draft target.",
        ),
        _gate(
            "target_post_id_matches",
            "Target post ID matches saved Atlas ref",
            bool(live_status and live_status.wordpress_post_id == page.wordpress_post_id),
            "The live WordPress target did not match the saved Atlas post ID.",
        ),
        _gate(
            "latest_update_hash_matches",
            "Latest update audit matches current Atlas payload",
            bool(latest_update and latest_update.payload_hash == current_payload_hash),
            "Latest successful update_draft audit payload hash must match current Atlas payload hash.",
        ),
        _gate(
            "slug_unique",
            "Slug has no conflicts",
            not export_package.slug_conflicts,
            "The suggested WordPress slug conflicts with another Atlas page.",
        ),
        _gate(
            "publish_status",
            "Publish payload status is forced to publish",
            publish_payload.status == "publish",
            "Publish dry-run payload status must be publish.",
        ),
        _gate(
            "no_media_upload",
            "No media upload requested",
            True,
            "Media upload is not available in publish dry run.",
        ),
        _gate(
            "one_page_only",
            "One page only",
            True,
            "Bulk publish is not available.",
        ),
    ]
    ready = all(gate.passed for gate in gates)
    token = None
    phrase = None
    expires_at = None
    if ready:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign_token(
            page_id=page_id,
            wordpress_post_id=page.wordpress_post_id or 0,
            payload_hash=publish_payload_hash,
            expires_at=expires,
        )
        phrase = f"PUBLISH WORDPRESS PAGE {publish_payload.slug}"
        expires_at = expires.isoformat()

    return WordPressPublishDryRun(
        page_id=page_id,
        status="dry_run_ready" if ready else "blocked",
        ready=ready,
        wordpress_post_id=page.wordpress_post_id,
        live_status=live_status,
        payload=publish_payload,
        current_payload_hash=current_payload_hash,
        latest_update_audit_hash=latest_update.payload_hash if latest_update else None,
        publish_payload_hash=publish_payload_hash,
        gate_results=gates,
        confirmation_token=token,
        confirmation_phrase=phrase,
        expires_at=expires_at,
    )


def _latest_successful_update_audit(session: Session, page_id: int) -> WordPressDraftAudit | None:
    return session.exec(
        select(WordPressDraftAudit)
        .where(
            WordPressDraftAudit.generated_page_id == page_id,
            WordPressDraftAudit.action_type == "update_draft",
            WordPressDraftAudit.status == "updated",
        )
        .order_by(WordPressDraftAudit.attempted_at.desc(), WordPressDraftAudit.id.desc())
    ).first()


def _gate(code: str, label: str, passed: bool, failure_message: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(
        code=code,
        label=label,
        passed=passed,
        message="Passed." if passed else failure_message,
    )


def _model_hash(payload: WordPressPublishRequestPayload) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sign_token(
    *,
    page_id: int,
    wordpress_post_id: int,
    payload_hash: str,
    expires_at: datetime,
) -> str:
    body = {
        "action": "publish_page",
        "page_id": page_id,
        "wordpress_post_id": wordpress_post_id,
        "payload_hash": payload_hash,
        "expires_at": int(expires_at.timestamp()),
        "nonce": secrets.token_hex(8),
    }
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _encode(hmac.new(_publish_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
