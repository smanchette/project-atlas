from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import secrets
from pathlib import Path

import httpx
from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import GeneratedPage, GeneratedPageRevision, WordPressDraftAudit, WordPressPublishAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressDraftRequestPayload,
    WordPressPublishDryRun,
    WordPressPublishApplyRequest,
    WordPressPublishApplyResult,
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


def apply_wordpress_publish(
    session: Session,
    page_id: int,
    confirmation: WordPressPublishApplyRequest,
) -> WordPressPublishApplyResult:
    token = _verify_token(confirmation.confirmation_token, page_id)
    dry_run = dry_run_wordpress_publish(session, page_id)
    expected_phrase = f"PUBLISH WORDPRESS PAGE {dry_run.payload.slug}"
    if not hmac.compare_digest(confirmation.confirmation_phrase.strip(), expected_phrase):
        raise HTTPException(status_code=422, detail="The confirmation phrase does not match the dry run.")
    if token["wordpress_post_id"] != dry_run.wordpress_post_id or token["payload_hash"] != dry_run.publish_payload_hash:
        raise HTTPException(status_code=409, detail="The publish target or payload changed after the dry run. Run a new dry run.")

    backup_gate = _backup_gate(confirmation.confirmed_backup_file, _latest_successful_update_audit(session, page_id))
    gates = [*dry_run.gate_results, backup_gate]
    if not dry_run.ready or not all(gate.passed for gate in gates):
        raise HTTPException(status_code=409, detail={"message": "WordPress publish is blocked.", "gate_results": [gate.model_dump(mode="json") for gate in gates]})

    page = session.get(GeneratedPage, page_id)
    settings = read_wordpress_settings(session)
    latest_update = _latest_successful_update_audit(session, page_id)
    if not page or not latest_update or page.wordpress_post_id is None:
        raise HTTPException(status_code=409, detail="Publish state changed after the dry run.")
    audit = WordPressPublishAudit(
        generated_page_id=page_id,
        wordpress_post_id=page.wordpress_post_id,
        wordpress_site_url=settings.site_url,
        status="pending",
        pre_publish_wordpress_status=dry_run.live_status.wordpress_status if dry_run.live_status else None,
        current_draft_payload_hash=dry_run.current_payload_hash,
        latest_update_audit_id=latest_update.id,
        latest_update_audit_hash=latest_update.payload_hash,
        publish_payload_hash=dry_run.publish_payload_hash,
        gate_results=[gate.model_dump(mode="json") for gate in gates],
        backup_file_name=confirmation.confirmed_backup_file,
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)

    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/pages/{page.wordpress_post_id}"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.post(
                endpoint,
                json=dry_run.payload.model_dump(mode="json"),
                auth=httpx.BasicAuth(settings.username, get_wordpress_application_password() or ""),
            )
    except httpx.HTTPError as exc:
        _finish_failed_audit(session, audit, f"WordPress publish request failed: {exc.__class__.__name__}.")
        raise HTTPException(status_code=502, detail="WordPress publish request failed.") from exc
    if response.status_code not in {200, 201}:
        _finish_failed_audit(session, audit, f"WordPress returned HTTP {response.status_code}.")
        raise HTTPException(status_code=502, detail=f"WordPress publish returned HTTP {response.status_code}.")
    try:
        data = response.json()
    except ValueError as exc:
        _finish_failed_audit(session, audit, "WordPress returned invalid JSON.")
        raise HTTPException(status_code=502, detail="WordPress publish returned invalid JSON.") from exc
    returned_id, returned_status, returned_url = data.get("id"), data.get("status"), data.get("link")
    if returned_id != page.wordpress_post_id or returned_status != "publish" or not _usable_public_url(returned_url, settings.site_url):
        _finish_failed_audit(session, audit, "WordPress did not confirm the expected published page, status, and public link.", returned_status, returned_url)
        raise HTTPException(status_code=502, detail="WordPress did not confirm the expected published page.")

    now = datetime.now(UTC)
    try:
        page.status = "published"
        page.wordpress_status = "publish"
        page.wordpress_url = returned_url
        page.last_wordpress_sync_at = now
        page.updated_at = now
        audit.status = "published"
        audit.completed_at = now
        audit.returned_wordpress_status = "publish"
        audit.returned_wordpress_url = returned_url
        session.add(page)
        session.add(audit)
        session.commit()
    except Exception as exc:
        session.rollback()
        try:
            persisted = session.get(WordPressPublishAudit, audit.id)
            if persisted:
                persisted.status = "reconciliation_required"
                persisted.returned_wordpress_status = "publish"
                persisted.returned_wordpress_url = returned_url
                persisted.error_message = "WordPress published successfully but Atlas could not finalize local state."
                session.add(persisted)
                session.commit()
        except Exception:
            session.rollback()
        raise HTTPException(status_code=500, detail="WordPress published, but Atlas requires manual reconciliation.") from exc
    session.refresh(audit)
    return WordPressPublishApplyResult(page_id=page_id, status="published", wordpress_post_id=returned_id, wordpress_status="publish", wordpress_url=returned_url, audit_id=audit.id or 0, publish_payload_hash=dry_run.publish_payload_hash, gate_results=gates)


def _verify_token(value: str, page_id: int) -> dict:
    try:
        encoded, supplied = value.split(".", 1)
        expected = _encode(hmac.new(_publish_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        body = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="The publish confirmation token is invalid.")
    if body.get("action") != "publish_page" or body.get("page_id") != page_id:
        raise HTTPException(status_code=422, detail="The publish confirmation token does not match this page.")
    if int(body.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status_code=422, detail="The publish confirmation token expired.")
    return body


def _backup_gate(file_name: str, latest_update: WordPressDraftAudit | None) -> WordPressDraftGateResult:
    try:
        path = resolve_backup_download(Path(file_name).name)
        if Path(file_name).name != file_name:
            raise BackupValidationError("Backup filename must not contain a path.")
        payload = load_backup(path)
        created = datetime.fromisoformat(payload["metadata"]["created_at"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=UTC)
        current = bool(latest_update and created >= _aware(latest_update.attempted_at))
        return _gate("confirmed_backup_current", "Confirmed data backup is valid and current", current, "A valid Data Backup JSON created after the latest successful draft update is required.")
    except (BackupValidationError, OSError, ValueError):
        return _gate("confirmed_backup_current", "Confirmed data backup is valid and current", False, "The confirmed Data Backup JSON is missing, invalid, or stale.")


def _finish_failed_audit(session: Session, audit: WordPressPublishAudit, message: str, status: str | None = None, url: str | None = None) -> None:
    audit.status = "failed"
    audit.completed_at = datetime.now(UTC)
    audit.returned_wordpress_status = status
    audit.returned_wordpress_url = url
    audit.error_message = message
    session.add(audit)
    session.commit()


def _usable_public_url(value: object, site_url: str) -> bool:
    return isinstance(value, str) and value.startswith(site_url.rstrip("/") + "/")


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


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
