from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import secrets
from typing import Any

import httpx
from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from app.models import GeneratedPage, GeneratedPageRevision, WordPressDraftAudit
from app.schemas.wordpress import (
    WordPressDraftUpdateApplyRequest,
    WordPressDraftUpdateApplyResult,
    WordPressDraftGateResult,
    WordPressDraftRequestPayload,
    WordPressDraftUpdateComparison,
    WordPressDraftUpdateDryRun,
)
from app.services.approval_audit import draft_content_hash
from app.services.page_export import build_page_export_package
from app.services.wordpress_draft_review import check_live_wordpress_draft_status
from app.services.wordpress_drafts import _payload_hash
from app.services.wordpress_sandbox import (
    build_wordpress_payload_preview,
    get_wordpress_application_password,
    read_wordpress_settings,
)

TOKEN_TTL_MINUTES = 15
_update_confirmation_secret = secrets.token_bytes(32)


def dry_run_wordpress_draft_update(session: Session, page_id: int) -> WordPressDraftUpdateDryRun:
    page = session.get(GeneratedPage, page_id)
    if not page:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Generated page not found")

    settings = read_wordpress_settings(session)
    export_package = build_page_export_package(session, page_id)
    preview = build_wordpress_payload_preview(session, page_id)
    payload = WordPressDraftRequestPayload(
        title=preview.payload.title,
        slug=preview.payload.slug,
        status="draft",
        content=preview.payload.content,
        excerpt=preview.payload.excerpt,
    )
    current_payload_hash = _payload_hash(payload)
    current_draft_hash = draft_content_hash(page.draft_content)
    latest_audit = _latest_successful_create_audit(session, page_id)
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
    password = get_wordpress_application_password()

    live_status = check_live_wordpress_draft_status(session, page_id) if page.wordpress_post_id else None
    media_hash = _media_reference_hash(preview.export_package.get("assigned_media") or [])
    comparison = WordPressDraftUpdateComparison(
        original_create_audit_id=latest_audit.id if latest_audit else None,
        original_payload_hash=latest_audit.payload_hash if latest_audit else None,
        current_payload_hash=current_payload_hash,
        original_draft_hash=latest_audit.draft_hash_at_attempt if latest_audit else None,
        current_draft_hash=current_draft_hash,
        payload_changed_since_create=bool(latest_audit and latest_audit.payload_hash != current_payload_hash),
        media_reference_hash=media_hash,
        media_reference_warning=_media_reference_warning(preview.export_package.get("assigned_media") or []),
        changed_summary=_changed_summary(
            page,
            payload=payload,
            current_payload_hash=current_payload_hash,
            current_draft_hash=current_draft_hash,
            latest_audit=latest_audit,
            live_status=live_status,
            media_warning=_media_reference_warning(preview.export_package.get("assigned_media") or []),
        ),
    )

    gates = [
        _gate(
            "sandbox_mode",
            "WordPress mode is sandbox",
            settings.publishing_mode == "sandbox",
            "WordPress publishing mode must be set to Sandbox.",
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
            "has_wordpress_ref",
            "Existing WordPress draft reference exists",
            page.wordpress_post_id is not None,
            "This Atlas page does not have a saved WordPress draft reference.",
        ),
        _gate(
            "atlas_wordpress_status_draft",
            "Saved Atlas WordPress status is draft",
            page.wordpress_status == "draft",
            f"Saved Atlas WordPress status is {page.wordpress_status or 'missing'}; only draft refs can be updated.",
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
            f"Live WordPress status is {(live_status.wordpress_status if live_status else None) or 'unknown'}; only draft pages can be updated.",
        ),
        _gate(
            "target_post_id_matches",
            "Target post ID matches saved Atlas ref",
            bool(live_status and live_status.wordpress_post_id == page.wordpress_post_id),
            "The live WordPress target did not match the saved Atlas post ID.",
        ),
        _gate(
            "export_clear",
            "Export package has no blockers",
            blocker_count == 0,
            f"Export package has {blocker_count} blocker warning(s).",
        ),
        _gate(
            "slug_unique",
            "Slug has no conflicts",
            not export_package.slug_conflicts,
            "The suggested WordPress slug conflicts with another Atlas page.",
        ),
        _gate(
            "draft_status",
            "Update payload status is forced to draft",
            payload.status == "draft",
            "WordPress update payload status must be draft.",
        ),
        _gate(
            "no_media_upload",
            "No media upload requested",
            True,
            "Media upload is not available in the update dry run.",
        ),
        _gate(
            "one_page_only",
            "One page only",
            True,
            "Bulk update is not available.",
        ),
    ]
    ready = all(gate.passed for gate in gates)
    token = None
    phrase = None
    expires_at = None
    if ready:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign_token(page_id, current_payload_hash, expires)
        phrase = f"UPDATE WORDPRESS DRAFT {payload.slug}"
        expires_at = expires.isoformat()

    return WordPressDraftUpdateDryRun(
        page_id=page_id,
        status="dry_run_ready" if ready else "blocked",
        ready=ready,
        wordpress_post_id=page.wordpress_post_id,
        live_status=live_status,
        payload=payload,
        comparison=comparison,
        gate_results=gates,
        confirmation_token=token,
        confirmation_phrase=phrase,
        expires_at=expires_at,
    )


def apply_wordpress_draft_update(
    session: Session,
    page_id: int,
    confirmation: WordPressDraftUpdateApplyRequest,
) -> WordPressDraftUpdateApplyResult:
    token = _verify_token(confirmation.confirmation_token, page_id)
    dry_run = dry_run_wordpress_draft_update(session, page_id)
    expected_phrase = _confirmation_phrase(dry_run.payload.slug)
    if not hmac.compare_digest(confirmation.confirmation_phrase.strip(), expected_phrase):
        raise HTTPException(status_code=422, detail="The confirmation phrase does not match the dry run.")
    if token["payload_hash"] != dry_run.comparison.current_payload_hash:
        dry_run.gate_results.append(
            WordPressDraftGateResult(
                code="dry_run_current",
                label="Dry run is current",
                passed=False,
                message="The WordPress update payload changed after the dry run. Run a new dry run.",
            )
        )

    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    settings = read_wordpress_settings(session)
    if not all(gate.passed for gate in dry_run.gate_results):
        audit = _record_update_audit(
            session,
            page=page,
            settings_site_url=settings.site_url,
            payload=dry_run.payload,
            payload_hash=dry_run.comparison.current_payload_hash,
            draft_hash=dry_run.comparison.current_draft_hash,
            gates=dry_run.gate_results,
            status="blocked",
            wordpress_post_id=page.wordpress_post_id,
            wordpress_status=page.wordpress_status,
            error_message="Confirmed update was blocked because one or more gates failed.",
        )
        session.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "WordPress draft update is blocked.",
                "audit_id": audit.id,
                "gate_results": [gate.model_dump(mode="json") for gate in dry_run.gate_results],
            },
        )

    password = get_wordpress_application_password()
    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/pages/{page.wordpress_post_id}"
    request_payload = dry_run.payload.model_dump(mode="json")
    request_payload["status"] = "draft"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            response = client.post(
                endpoint,
                json=request_payload,
                auth=httpx.BasicAuth(settings.username, password or ""),
            )
    except httpx.HTTPError as exc:
        _record_update_audit(
            session,
            page=page,
            settings_site_url=settings.site_url,
            payload=dry_run.payload,
            payload_hash=dry_run.comparison.current_payload_hash,
            draft_hash=dry_run.comparison.current_draft_hash,
            gates=dry_run.gate_results,
            status="failed",
            wordpress_post_id=page.wordpress_post_id,
            wordpress_status=page.wordpress_status,
            error_message=f"WordPress request failed: {exc.__class__.__name__}.",
        )
        session.commit()
        raise HTTPException(status_code=502, detail="WordPress draft update request failed.") from exc

    if response.status_code not in {200, 201}:
        _record_update_audit(
            session,
            page=page,
            settings_site_url=settings.site_url,
            payload=dry_run.payload,
            payload_hash=dry_run.comparison.current_payload_hash,
            draft_hash=dry_run.comparison.current_draft_hash,
            gates=dry_run.gate_results,
            status="failed",
            wordpress_post_id=page.wordpress_post_id,
            wordpress_status=page.wordpress_status,
            error_message=f"WordPress returned HTTP {response.status_code}.",
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail=f"WordPress draft update returned HTTP {response.status_code}.",
        )

    try:
        response_data = response.json()
    except ValueError:
        response_data = {}
    post_id = response_data.get("id")
    wordpress_status = response_data.get("status")
    if post_id != page.wordpress_post_id or wordpress_status != "draft":
        _record_update_audit(
            session,
            page=page,
            settings_site_url=settings.site_url,
            payload=dry_run.payload,
            payload_hash=dry_run.comparison.current_payload_hash,
            draft_hash=dry_run.comparison.current_draft_hash,
            gates=dry_run.gate_results,
            status="failed",
            wordpress_post_id=post_id if isinstance(post_id, int) else page.wordpress_post_id,
            wordpress_status=wordpress_status if isinstance(wordpress_status, str) else None,
            error_message="WordPress did not confirm that the updated target is the saved draft page.",
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail="WordPress did not confirm that the updated page remains a draft.",
        )

    now = datetime.now(UTC)
    wordpress_url = response_data.get("link")
    page.wordpress_status = "draft"
    if isinstance(wordpress_url, str):
        page.wordpress_url = wordpress_url
    page.last_wordpress_sync_at = now
    page.updated_at = now
    audit = _record_update_audit(
        session,
        page=page,
        settings_site_url=settings.site_url,
        payload=dry_run.payload,
        payload_hash=dry_run.comparison.current_payload_hash,
        draft_hash=dry_run.comparison.current_draft_hash,
        gates=dry_run.gate_results,
        status="updated",
        wordpress_post_id=post_id,
        wordpress_status="draft",
    )
    session.add(page)
    session.commit()
    session.refresh(audit)
    return WordPressDraftUpdateApplyResult(
        page_id=page_id,
        status="updated",
        wordpress_post_id=post_id,
        wordpress_status="draft",
        wordpress_url=page.wordpress_url,
        audit_id=audit.id or 0,
        payload_hash=dry_run.comparison.current_payload_hash,
        gate_results=dry_run.gate_results,
    )


def _latest_successful_create_audit(session: Session, page_id: int) -> WordPressDraftAudit | None:
    return session.exec(
        select(WordPressDraftAudit)
        .where(
            WordPressDraftAudit.generated_page_id == page_id,
            WordPressDraftAudit.action_type == "create_draft",
            WordPressDraftAudit.status == "created",
        )
        .order_by(WordPressDraftAudit.attempted_at.desc(), WordPressDraftAudit.id.desc())
    ).first()


def _changed_summary(
    page: GeneratedPage,
    *,
    payload: WordPressDraftRequestPayload,
    current_payload_hash: str,
    current_draft_hash: str,
    latest_audit: WordPressDraftAudit | None,
    live_status: Any,
    media_warning: str | None,
) -> list[str]:
    changes: list[str] = []
    if latest_audit is None:
        changes.append("No successful create_draft audit is available for original payload comparison.")
    elif latest_audit.payload_hash != current_payload_hash:
        changes.append("Current Atlas WordPress payload hash differs from the original create_draft audit hash.")
    else:
        changes.append("Current Atlas WordPress payload hash matches the original create_draft audit hash.")
    if latest_audit and latest_audit.draft_hash_at_attempt != current_draft_hash:
        changes.append("Atlas draft content hash differs from the original create_draft audit draft hash.")
    if live_status and not live_status.error_message:
        if live_status.wordpress_title and _strip_html(live_status.wordpress_title) != payload.title:
            changes.append("Live WordPress title differs from the current Atlas payload title.")
        if live_status.wordpress_slug and live_status.wordpress_slug != payload.slug:
            changes.append("Live WordPress slug differs from the current Atlas payload slug.")
        if live_status.wordpress_status != "draft":
            changes.append("Live WordPress status is not draft.")
    if page.wordpress_status != "draft":
        changes.append("Saved Atlas WordPress status is not draft.")
    if media_warning:
        changes.append(media_warning)
    return changes


def _media_reference_hash(media: list[Any]) -> str:
    canonical = json.dumps(media, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _media_reference_warning(media: list[Any]) -> str | None:
    if not media:
        return None
    return (
        "Current export includes media references and assignment-level alt text. "
        "Original create_draft audits did not store a separate media-reference hash, "
        "so media/alt changes may not be reflected in the WordPress payload hash."
    )


def _gate(code: str, label: str, passed: bool, failure_message: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(
        code=code,
        label=label,
        passed=passed,
        message="Passed." if passed else failure_message,
    )


def _sign_token(page_id: int, payload_hash: str, expires_at: datetime) -> str:
    body = {
        "action": "update_draft",
        "page_id": page_id,
        "payload_hash": payload_hash,
        "expires_at": int(expires_at.timestamp()),
        "nonce": secrets.token_hex(8),
    }
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _encode(hmac.new(_update_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _verify_token(token: str, page_id: int) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _encode(
            hmac.new(_update_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        payload = json.loads(_decode(encoded))
        if payload.get("action") != "update_draft":
            raise ValueError
        if payload.get("page_id") != page_id:
            raise ValueError
        if not isinstance(payload.get("payload_hash"), str):
            raise ValueError
        if int(payload.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()):
            raise HTTPException(status_code=409, detail="The dry-run confirmation token expired.")
        return payload
    except HTTPException:
        raise
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="A valid dry-run confirmation token is required.",
        ) from exc


def _record_update_audit(
    session: Session,
    *,
    page: GeneratedPage,
    settings_site_url: str,
    payload: WordPressDraftRequestPayload,
    payload_hash: str,
    draft_hash: str,
    gates: list[WordPressDraftGateResult],
    status: str,
    wordpress_post_id: int | None,
    wordpress_status: str | None,
    error_message: str | None = None,
) -> WordPressDraftAudit:
    audit = WordPressDraftAudit(
        generated_page_id=page.id,
        action_type="update_draft",
        status=status,
        wordpress_site_url=settings_site_url,
        wordpress_post_id=wordpress_post_id,
        wordpress_status=wordpress_status,
        slug=payload.slug,
        payload_hash=payload_hash,
        qa_status_at_attempt=page.qa_status,
        qa_checked_at=page.qa_checked_at,
        draft_hash_at_attempt=draft_hash,
        gate_results=[gate.model_dump(mode="json") for gate in gates],
        error_message=error_message,
    )
    session.add(audit)
    session.flush()
    return audit


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def _confirmation_phrase(slug: str) -> str:
    return f"UPDATE WORDPRESS DRAFT {slug}"


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()


def _strip_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]*>", "", value).strip()
