import base64
from datetime import UTC, datetime, timedelta
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
    WordPressDraftCreateRequest,
    WordPressDraftCreateResult,
    WordPressDraftDryRun,
    WordPressDraftGateResult,
    WordPressDraftRequestPayload,
)
from app.services.approval_audit import draft_content_hash
from app.services.page_export import build_page_export_package
from app.services.wordpress_http import wordpress_basic_auth, wordpress_http_client
from app.services.wordpress_sandbox import (
    build_wordpress_payload_preview,
    get_wordpress_application_password,
    read_wordpress_settings,
)

TOKEN_TTL_MINUTES = 15
_confirmation_secret = secrets.token_bytes(32)


def dry_run_wordpress_draft(session: Session, page_id: int) -> WordPressDraftDryRun:
    context = _build_context(session, page_id)
    ready = all(gate.passed for gate in context["gates"])
    token = None
    phrase = None
    expires_at = None
    if ready:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign_token(page_id, context["payload_hash"], expires)
        phrase = _confirmation_phrase(context["payload"].slug)
        expires_at = expires.isoformat()
    return WordPressDraftDryRun(
        page_id=page_id,
        status="dry_run_ready" if ready else "blocked",
        ready=ready,
        payload=context["payload"],
        payload_hash=context["payload_hash"],
        draft_hash=context["draft_hash"],
        gate_results=context["gates"],
        confirmation_token=token,
        confirmation_phrase=phrase,
        expires_at=expires_at,
    )


def create_wordpress_draft(
    session: Session,
    page_id: int,
    confirmation: WordPressDraftCreateRequest,
) -> WordPressDraftCreateResult:
    token = _verify_token(confirmation.confirmation_token, page_id)
    context = _build_context(session, page_id)
    expected_phrase = _confirmation_phrase(context["payload"].slug)
    if not hmac.compare_digest(confirmation.confirmation_phrase.strip(), expected_phrase):
        raise HTTPException(status_code=422, detail="The confirmation phrase does not match the dry run.")
    if token["payload_hash"] != context["payload_hash"]:
        context["gates"].append(
            WordPressDraftGateResult(
                code="dry_run_current",
                label="Dry run is current",
                passed=False,
                message="The WordPress payload changed after the dry run. Run a new dry run.",
            )
        )

    if not all(gate.passed for gate in context["gates"]):
        audit = _record_audit(
            session,
            context,
            status="blocked",
            error_message="Confirmed creation was blocked because one or more gates failed.",
        )
        session.commit()
        raise HTTPException(
            status_code=409,
            detail={
                "message": "WordPress draft creation is blocked.",
                "audit_id": audit.id,
                "gate_results": [gate.model_dump(mode="json") for gate in context["gates"]],
            },
        )

    settings = context["settings"]
    password = get_wordpress_application_password()
    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/pages"
    request_payload = context["payload"].model_dump(mode="json")
    request_payload["status"] = "draft"
    try:
        with wordpress_http_client(settings.site_url, timeout=15.0, follow_redirects=True, client_factory=httpx.Client) as client:
            response = client.post(
                endpoint,
                json=request_payload,
                auth=wordpress_basic_auth(settings.username, password or ""),
            )
    except httpx.HTTPError as exc:
        _record_audit(
            session,
            context,
            status="failed",
            error_message=f"WordPress request failed: {exc.__class__.__name__}.",
        )
        session.commit()
        raise HTTPException(status_code=502, detail="WordPress draft creation request failed.") from exc

    if response.status_code not in {200, 201}:
        _record_audit(
            session,
            context,
            status="failed",
            error_message=f"WordPress returned HTTP {response.status_code}.",
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail=f"WordPress draft creation returned HTTP {response.status_code}.",
        )

    try:
        response_data = response.json()
    except ValueError as exc:
        response_data = {}
    post_id = response_data.get("id")
    wordpress_status = response_data.get("status")
    if not isinstance(post_id, int) or wordpress_status != "draft":
        _record_audit(
            session,
            context,
            status="failed",
            wordpress_post_id=post_id if isinstance(post_id, int) else None,
            wordpress_status=wordpress_status if isinstance(wordpress_status, str) else None,
            error_message="WordPress did not return a valid draft page response.",
        )
        session.commit()
        raise HTTPException(
            status_code=502,
            detail="WordPress did not confirm that the created page is a draft.",
        )

    now = datetime.now(UTC)
    page = context["page"]
    wordpress_url = response_data.get("link")
    page.wordpress_post_id = post_id
    page.wordpress_url = wordpress_url if isinstance(wordpress_url, str) else None
    page.wordpress_status = "draft"
    page.wordpress_created_at = now
    page.last_wordpress_sync_at = now
    page.updated_at = now
    audit = _record_audit(
        session,
        context,
        status="created",
        wordpress_post_id=post_id,
        wordpress_status="draft",
    )
    session.add(page)
    session.commit()
    session.refresh(audit)
    return WordPressDraftCreateResult(
        page_id=page_id,
        status="created",
        wordpress_post_id=post_id,
        wordpress_status="draft",
        wordpress_url=page.wordpress_url,
        audit_id=audit.id or 0,
        payload_hash=context["payload_hash"],
        gate_results=context["gates"],
    )


def _build_context(session: Session, page_id: int) -> dict[str, Any]:
    page = session.get(GeneratedPage, page_id)
    if not page:
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
    payload_hash = _payload_hash(payload)
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
    gates = [
        _gate(
            "sandbox_mode",
            "WordPress mode is sandbox",
            settings.publishing_mode == "sandbox",
            "WordPress publishing mode must be set to Sandbox.",
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
            "Payload status is draft",
            payload.status == "draft",
            "WordPress payload status must be draft.",
        ),
        _gate(
            "credentials_ready",
            "Connection credentials are available",
            bool(settings.site_url and settings.username and password),
            "Site URL, username, and the process-memory application password are required.",
        ),
        _gate(
            "not_already_created",
            "No existing WordPress draft reference",
            page.wordpress_post_id is None,
            "This Atlas page already has a WordPress post reference; updates are not supported.",
        ),
    ]
    return {
        "page": page,
        "settings": settings,
        "payload": payload,
        "payload_hash": payload_hash,
        "draft_hash": draft_content_hash(page.draft_content),
        "gates": gates,
    }


def _record_audit(
    session: Session,
    context: dict[str, Any],
    *,
    status: str,
    wordpress_post_id: int | None = None,
    wordpress_status: str | None = None,
    error_message: str | None = None,
) -> WordPressDraftAudit:
    page = context["page"]
    audit = WordPressDraftAudit(
        generated_page_id=page.id,
        action_type="create_draft",
        status=status,
        wordpress_site_url=context["settings"].site_url,
        wordpress_post_id=wordpress_post_id,
        wordpress_status=wordpress_status,
        slug=context["payload"].slug,
        payload_hash=context["payload_hash"],
        qa_status_at_attempt=page.qa_status,
        qa_checked_at=page.qa_checked_at,
        draft_hash_at_attempt=context["draft_hash"],
        gate_results=[gate.model_dump(mode="json") for gate in context["gates"]],
        error_message=error_message,
    )
    session.add(audit)
    session.flush()
    return audit


def _gate(code: str, label: str, passed: bool, failure_message: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(
        code=code,
        label=label,
        passed=passed,
        message="Passed." if passed else failure_message,
    )


def _payload_hash(payload: WordPressDraftRequestPayload) -> str:
    canonical = json.dumps(
        payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _confirmation_phrase(slug: str) -> str:
    return f"CREATE WORDPRESS DRAFT {slug}"


def _sign_token(page_id: int, payload_hash: str, expires_at: datetime) -> str:
    body = {
        "page_id": page_id,
        "payload_hash": payload_hash,
        "expires_at": int(expires_at.timestamp()),
        "nonce": secrets.token_hex(8),
    }
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _encode(hmac.new(_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _verify_token(token: str, page_id: int) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _encode(
            hmac.new(_confirmation_secret, encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(supplied_signature, expected_signature):
            raise ValueError
        payload = json.loads(_decode(encoded))
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


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode(value: str) -> str:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding).decode("utf-8")


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.timestamp()
