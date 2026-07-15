from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
from threading import Lock, Timer
from typing import Any

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import GeneratedPage, WordPressHeadingCorrectionAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressHeadingContentPayload,
    WordPressHeadingCorrectionApplyRequest,
    WordPressHeadingCorrectionApplyResult,
    WordPressHeadingCorrectionBackupIdentities,
    WordPressHeadingCorrectionDryRun,
    WordPressHeadingCorrectionDryRunRequest,
    WordPressHeadingCorrectionObservationResult,
    WordPressHeadingCorrectionReconcileRequest,
    WordPressHeadingCorrectionReconcileResult,
    WordPressHeadingCorrectionVerification,
    WordPressHeadingCorrectionVerifyRequest,
)
from app.services.wordpress_deployment_release import (
    DeploymentReleaseError,
    resolve_program_root,
    verify_runtime_release_identity,
)
from app.services.wordpress_heading_contract import (
    ATLAS_PAGE_ID,
    CURRENT_HEADING_FRAGMENT,
    EXPECTED_CURRENT_BODY_HASH,
    EXPECTED_FEATURED_MEDIA,
    EXPECTED_SLUG,
    EXPECTED_TITLE,
    EXPECTED_URL,
    PROPOSED_HEADING_FRAGMENT,
    WORDPRESS_POST_ID,
    _headings,
    build_orlando_heading_correction_dry_run,
    wordpress_body_hash,
)
from app.services.wordpress_sandbox import (
    get_wordpress_application_password,
    read_wordpress_settings,
)
from app.services.wordpress_rendered_state import (
    BOT_PATTERN,
    EXPECTED_MEDIA_ALT,
    EXPECTED_MEDIA_URL,
    EXPECTED_TITLE as EXPECTED_RENDERED_DOCUMENT_TITLE,
    validate_manual_browser_evidence,
)

EXPECTED_PROPOSED_BODY_HASH = "c031a7aa841b8e9a0316956dd3bf25178f390e64d01ceb9d9cd4273cc4aed195"
EXPECTED_RENDERED_H1 = "Drywood Termite Tenting in Orlando, FL"
CONFIRMATION_PHRASE = "CORRECT ORLANDO DUPLICATE H1"
RECONCILIATION_PHRASE = "FINALIZE ORLANDO H1 CORRECTION AUDIT"
TOKEN_TTL_MINUTES = 10
BACKUP_MAX_AGE = timedelta(hours=24)
TOKEN_ACTION = "correct_orlando_duplicate_h1"
_token_secret = secrets.token_bytes(32)


@dataclass(frozen=True)
class _TokenHandleEntry:
    raw_token: str
    action: str
    atlas_page_id: int
    wordpress_post_id: int
    issued_at: datetime
    expires_at: datetime
    proposed_body_hash: str
    backup_digest: str
    release_digest: str
    manual_browser_evidence: dict[str, Any] | None


@dataclass(frozen=True)
class _ConsumedTokenContext:
    action: str
    atlas_page_id: int
    wordpress_post_id: int
    proposed_body_hash: str
    backup_digest: str
    release_digest: str
    manual_browser_evidence: dict[str, Any] | None


_token_handle_lock = Lock()
_token_handles: dict[str, _TokenHandleEntry] = {}
_token_handle_timers: dict[str, Timer] = {}


def dry_run_heading_correction(
    session: Session,
    page_id: int,
    request: WordPressHeadingCorrectionDryRunRequest,
    *,
    issue_token_handle: bool = True,
) -> WordPressHeadingCorrectionDryRun:
    page = session.get(GeneratedPage, page_id)
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    observation = _observe(
        settings.site_url,
        settings.username,
        password,
        manual_evidence=request.manual_browser_evidence,
    )
    page_observation = _observation_diagnostic(observation, "page_8_observation", bool(observation.get("page")))
    legacy_snapshot = observation.get("snapshot") if isinstance(observation.get("snapshot"), dict) else {}
    media31_observation = _observation_diagnostic(observation, "media_31_observation", bool(observation.get("media_31") or legacy_snapshot.get("media_31")))
    media32_observation = _observation_diagnostic(observation, "media_32_observation", bool(observation.get("media_32") or legacy_snapshot.get("media_32")))
    rendered_observation = _observation_diagnostic(
        observation,
        "rendered_page_observation",
        bool(observation.get("rendered_html") or observation.get("rendered_h1_inventory")),
    )
    plan = build_orlando_heading_correction_dry_run(
        observation.get("page") if page_observation.success else None,
        observation.get("rendered_html", "") if rendered_observation.success else "",
        observation.get("rendered_h1_inventory") if rendered_observation.success else None,
    )
    plan.page_8_observation = page_observation
    plan.media_31_observation = media31_observation
    plan.media_32_observation = media32_observation
    plan.rendered_page_observation = rendered_observation
    release, release_error = _release_identity()
    page_data = observation.get("page") if isinstance(observation.get("page"), dict) else {}
    media31 = observation.get("media_31") if isinstance(observation.get("media_31"), dict) else legacy_snapshot.get("media_31", {})
    media32 = observation.get("media_32") if isinstance(observation.get("media_32"), dict) else legacy_snapshot.get("media_32", {})
    rendered_snapshot = observation.get("rendered_snapshot") if isinstance(observation.get("rendered_snapshot"), dict) else legacy_snapshot.get("rendered", {})
    body = _text(page_data.get("content"))
    extra_gates = [
        _gate(
            "atlas_target",
            "Atlas page 41 maps only to WordPress page 8",
            bool(page_id == ATLAS_PAGE_ID and page and page.wordpress_post_id == WORDPRESS_POST_ID),
            "Atlas page 41 and its saved WordPress page 8 mapping are required.",
        ),
        _gate(
            "credentials",
            "WordPress application-password credentials are available in process memory",
            bool(settings.site_url and settings.username and password),
            "WordPress credentials are missing from backend process memory.",
        ),
        _observation_gate("page_8_observation", "Authenticated WordPress page 8 GET succeeded", page_observation),
        _observation_gate("media_31_observation", "Authenticated WordPress media 31 GET succeeded", media31_observation),
        _observation_gate("media_32_observation", "Authenticated WordPress media 32 GET succeeded", media32_observation),
        _observation_gate("rendered_page_observation", "Rendered Orlando page observation succeeded", rendered_observation),
        _gate(
            "rendered_identity",
            "Rendered title, canonical, featured image, and alt remain exact",
            bool(
                rendered_observation.success
                and rendered_snapshot.get("document_title") == EXPECTED_RENDERED_DOCUMENT_TITLE
                and rendered_snapshot.get("canonical") == EXPECTED_URL
                and rendered_snapshot.get("featured_image_url") == EXPECTED_MEDIA_URL
                and rendered_snapshot.get("featured_image_alt") == EXPECTED_MEDIA_ALT
            ),
            "blocked_due_to_missing_rendered_observation" if not rendered_observation.success else "Rendered title, canonical, image, or alt drifted.",
        ),
        _gate(
            "rendered_metadata_absence",
            "Rendered metadata and media 32 remain absent",
            bool(rendered_observation.success and rendered_snapshot.get("metadata_count") == 0 and rendered_snapshot.get("media_32_visible") is False),
            "blocked_due_to_missing_rendered_observation" if not rendered_observation.success else "Unexpected metadata or media 32 appeared.",
        ),
        _gate(
            "media_31_identity",
            "Media 31 remains the locked visible featured image",
            bool(
                media31_observation.success
                and media31.get("id") == 31
                and media31.get("source_url") == EXPECTED_MEDIA_URL
                and media31.get("alt_text") == EXPECTED_MEDIA_ALT
                and page_data.get("featured_media") == 31
                and rendered_snapshot.get("media_31_visible") is True
            ),
            "blocked_due_to_missing_media_31_observation" if not media31_observation.success else "Media 31 identity or visibility drifted.",
        ),
        _gate(
            "media_32_identity",
            "Media 32 remains unattached, unfeatured, and absent",
            bool(
                media32_observation.success
                and media32.get("id") == 32
                and media32.get("post") in {None, 0}
                and page_data.get("featured_media") != 32
                and str(media32.get("source_url", "")) not in body
                and rendered_snapshot.get("media_32_visible") is False
            ),
            "blocked_due_to_missing_media_32_observation" if not media32_observation.success else "Media 32 attachment, feature, body, or rendered absence drifted.",
        ),
        _gate(
            "proposed_body_hash",
            "Proposed canonical body hash matches the locked value",
            plan.proposed_body_hash == EXPECTED_PROPOSED_BODY_HASH,
            "The proposed body hash drifted from the locked correction.",
        ),
        _gate(
            "fresh_backup_identities",
            "Fresh Atlas Data, Media, and Program backup identities are supplied",
            _backups_are_fresh(request.backups),
            "All three correctly named Atlas backups must be no more than 24 hours old.",
        ),
        _gate(
            "release_identity",
            "Runtime release identity is independently verified",
            release is not None,
            release_error or "release_identity_unavailable",
        ),
    ]
    plan.gate_results.extend(extra_gates)
    plan.ready = plan.ready and all(gate.passed for gate in extra_gates)
    plan.status = "dry_run_ready" if plan.ready else "blocked"
    plan.backup_identities = request.backups
    plan.release_identity = release
    plan.pre_snapshot = observation.get("snapshot")
    if plan.ready and release and plan.pre_snapshot and issue_token_handle:
        issued = datetime.now(UTC)
        expires = issued + timedelta(minutes=TOKEN_TTL_MINUTES)
        token_body = {
            "action": TOKEN_ACTION,
            "atlas_page_id": ATLAS_PAGE_ID,
            "wordpress_post_id": WORDPRESS_POST_ID,
            "current_body_hash": EXPECTED_CURRENT_BODY_HASH,
            "proposed_body_hash": EXPECTED_PROPOSED_BODY_HASH,
            "backup_digest": _digest(request.backups.model_dump(mode="json")),
            "release_digest": _digest(release),
            "snapshot_digest": _digest(plan.pre_snapshot),
            "expires_at": int(expires.timestamp()),
            "jti": secrets.token_hex(16),
        }
        raw_token = _sign(token_body)
        plan.token_handle = _store_token_handle(
            raw_token,
            token_body,
            issued_at=issued,
            expires_at=expires,
            manual_browser_evidence=(
                request.manual_browser_evidence.model_dump(mode="json", exclude_none=True)
                if request.manual_browser_evidence is not None
                else None
            ),
        )
        plan.confirmation_phrase = CONFIRMATION_PHRASE
        plan.expires_at = expires.isoformat()
        plan.token_issued = True  # type: ignore[assignment]
    return plan


def apply_heading_correction(
    session: Session,
    page_id: int,
    request: WordPressHeadingCorrectionApplyRequest,
) -> WordPressHeadingCorrectionApplyResult:
    raw_token, handle_context = _consume_token_handle(
        request.token_handle,
        page_id,
        request.backups,
    )
    try:
        token = _verify_token(raw_token, page_id)
        fingerprint = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    finally:
        raw_token = ""
    if not hmac.compare_digest(request.confirmation_phrase.strip(), CONFIRMATION_PHRASE):
        raise HTTPException(422, "The heading-correction confirmation phrase is incorrect.")
    dry = dry_run_heading_correction(
        session,
        page_id,
        WordPressHeadingCorrectionDryRunRequest(
            backups=request.backups,
            manual_browser_evidence=handle_context.manual_browser_evidence,
        ),
        issue_token_handle=False,
    )
    if not dry.ready or not dry.pre_snapshot or not dry.release_identity:
        raise HTTPException(409, {"message": "Heading correction is blocked.", "gate_results": _dump_gates(dry.gate_results)})
    expected = {
        "backup_digest": _digest(request.backups.model_dump(mode="json")),
        "release_digest": _digest(dry.release_identity),
        "snapshot_digest": _digest(dry.pre_snapshot),
        "current_body_hash": EXPECTED_CURRENT_BODY_HASH,
        "proposed_body_hash": EXPECTED_PROPOSED_BODY_HASH,
    }
    if any(token.get(key) != value for key, value in expected.items()):
        raise HTTPException(409, "The target, backups, release identity, or live snapshot changed after dry run.")
    if (
        handle_context.action != TOKEN_ACTION
        or handle_context.atlas_page_id != ATLAS_PAGE_ID
        or handle_context.wordpress_post_id != WORDPRESS_POST_ID
        or handle_context.proposed_body_hash != EXPECTED_PROPOSED_BODY_HASH
        or handle_context.backup_digest != expected["backup_digest"]
        or handle_context.release_digest != expected["release_digest"]
    ):
        raise HTTPException(409, "The token handle binding does not match the guarded correction context.")

    if session.exec(
        select(WordPressHeadingCorrectionAudit).where(
            WordPressHeadingCorrectionAudit.token_fingerprint == fingerprint
        )
    ).first():
        raise HTTPException(409, "This heading-correction token was already used; it will not be replayed.")

    settings = read_wordpress_settings(session)
    audit = WordPressHeadingCorrectionAudit(
        generated_page_id=ATLAS_PAGE_ID,
        wordpress_post_id=WORDPRESS_POST_ID,
        status="pending",
        wordpress_site_url=settings.site_url,
        current_body_hash=EXPECTED_CURRENT_BODY_HASH,
        proposed_body_hash=EXPECTED_PROPOSED_BODY_HASH,
        token_fingerprint=fingerprint,
        backup_identities=request.backups.model_dump(mode="json"),
        release_identity=dry.release_identity,
        pre_snapshot=dry.pre_snapshot,
        gate_results=_dump_gates(dry.gate_results),
        wordpress_write_count=0,
    )
    session.add(audit)
    session.commit()
    session.refresh(audit)

    payload = WordPressHeadingContentPayload(**dry.request_payload)
    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/pages/{WORDPRESS_POST_ID}"
    try:
        with httpx.Client(timeout=15.0, follow_redirects=False) as client:
            response = client.post(
                endpoint,
                json=payload.model_dump(mode="json"),
                auth=httpx.BasicAuth(settings.username, get_wordpress_application_password() or ""),
            )
    except httpx.HTTPError as exc:
        _mark_reconciliation_required(session, audit, f"WordPress response was uncertain: {exc.__class__.__name__}.", 1)
        raise HTTPException(502, {"message": "WordPress outcome is uncertain; do not retry. Use reconciliation.", "audit_id": audit.id}) from exc

    audit.wordpress_write_count = 1
    if response.status_code not in {200, 201}:
        _finish_audit(session, audit, "failed", f"WordPress returned HTTP {response.status_code}.")
        raise HTTPException(502, {"message": "WordPress rejected the one-field correction request; do not retry automatically.", "audit_id": audit.id})
    try:
        returned = response.json()
    except ValueError as exc:
        _mark_reconciliation_required(session, audit, "WordPress returned invalid JSON after the write.", 1)
        raise HTTPException(502, {"message": "WordPress outcome requires reconciliation; do not retry.", "audit_id": audit.id}) from exc
    returned_snapshot = _page_snapshot(returned)
    pre_page = dry.pre_snapshot["page"]
    returned_invariants = ("title", "slug", "link", "status", "excerpt", "featured_media")
    response_verified = bool(
        returned.get("id") == WORDPRESS_POST_ID
        and returned_snapshot["body_hash"] == EXPECTED_PROPOSED_BODY_HASH
        and all(returned_snapshot[field] == pre_page[field] for field in returned_invariants)
    )
    if not response_verified:
        _mark_reconciliation_required(session, audit, "WordPress did not return the exact corrected page and unchanged protected fields.", 1)
        raise HTTPException(502, {"message": "WordPress outcome requires reconciliation; do not retry.", "audit_id": audit.id})

    post = _observe(settings.site_url, settings.username, get_wordpress_application_password())
    verify = _verify_corrected_observation(post, dry.pre_snapshot, audit.id)
    if not verify.verified:
        audit.post_snapshot = post.get("snapshot")
        _mark_reconciliation_required(session, audit, "Post-write verification did not prove the locked correction.", 1)
        raise HTTPException(502, {"message": "The write occurred but verification failed; do not retry. Use reconciliation.", "audit_id": audit.id, "gate_results": _dump_gates(verify.gate_results)})
    try:
        audit.status = "corrected"
        audit.completed_at = datetime.now(UTC)
        audit.post_snapshot = post["snapshot"]
        audit.gate_results = _dump_gates(verify.gate_results)
        session.add(audit)
        session.commit()
    except Exception as exc:
        session.rollback()
        _recover_partial_finalization(session, audit.id or 0, post.get("snapshot"))
        raise HTTPException(500, {"message": "WordPress succeeded but Atlas finalization failed; do not resend the write. Use reconciliation.", "audit_id": audit.id}) from exc
    return WordPressHeadingCorrectionApplyResult(
        status="corrected",
        audit_id=audit.id or 0,
        current_body_hash=EXPECTED_CURRENT_BODY_HASH,
        proposed_body_hash=EXPECTED_PROPOSED_BODY_HASH,
        request_payload=payload,
        gate_results=verify.gate_results,
    )


def verify_heading_correction(
    session: Session,
    page_id: int,
    request: WordPressHeadingCorrectionVerifyRequest,
) -> WordPressHeadingCorrectionVerification:
    _target(page_id)
    settings = read_wordpress_settings(session)
    observation = _observe(settings.site_url, settings.username, get_wordpress_application_password())
    audit = session.get(WordPressHeadingCorrectionAudit, request.audit_id) if request.audit_id else None
    pre_snapshot = audit.pre_snapshot if audit else None
    result = _verify_corrected_observation(observation, pre_snapshot, audit.id if audit else None)
    if result.verified and audit and audit.status == "reconciliation_required":
        result.status = "reconciliation_ready"
    return result


def reconcile_heading_correction(
    session: Session,
    page_id: int,
    request: WordPressHeadingCorrectionReconcileRequest,
) -> WordPressHeadingCorrectionReconcileResult:
    _target(page_id)
    if not hmac.compare_digest(request.confirmation_phrase.strip(), RECONCILIATION_PHRASE):
        raise HTTPException(422, "The reconciliation phrase is incorrect.")
    audit = session.get(WordPressHeadingCorrectionAudit, request.audit_id)
    if not audit or audit.generated_page_id != ATLAS_PAGE_ID or audit.wordpress_post_id != WORDPRESS_POST_ID:
        raise HTTPException(404, "Heading-correction audit not found.")
    if audit.status != "reconciliation_required":
        raise HTTPException(409, "Only a reconciliation-required correction audit can be finalized.")
    verification = verify_heading_correction(
        session, page_id, WordPressHeadingCorrectionVerifyRequest(audit_id=audit.id)
    )
    if not verification.verified:
        raise HTTPException(409, {"message": "Live read-only evidence does not prove the correction.", "gate_results": _dump_gates(verification.gate_results)})
    audit.status = "verified"
    audit.completed_at = datetime.now(UTC)
    audit.post_snapshot = verification.snapshot
    audit.gate_results = _dump_gates(verification.gate_results)
    session.add(audit)
    session.commit()
    return WordPressHeadingCorrectionReconcileResult(audit_id=audit.id or 0, gate_results=verification.gate_results)


def _observe(
    site_url: str,
    username: str,
    password: str | None,
    *,
    manual_evidence: Any | None = None,
) -> dict[str, Any]:
    base = site_url.rstrip("/")
    urls = {
        "page_8_observation": f"{base}/wp-json/wp/v2/pages/{WORDPRESS_POST_ID}?context=edit",
        "media_31_observation": f"{base}/wp-json/wp/v2/media/31?context=edit",
        "media_32_observation": f"{base}/wp-json/wp/v2/media/32?context=edit",
    }
    if not (site_url and username and password):
        unavailable = {
            key: _diagnostic(False, "not_attempted", False, "credentials_unavailable", "WordPress credentials are unavailable in backend process memory.")
            for key in (*urls, "rendered_page_observation")
        }
        return {**unavailable, "page": None, "media_31": None, "media_32": None, "rendered_html": ""}

    auth = httpx.BasicAuth(username, password)
    result: dict[str, Any] = {"page": None, "media_31": None, "media_32": None, "rendered_html": ""}
    with httpx.Client(timeout=15.0, follow_redirects=False) as client:
        for key, url in urls.items():
            resource_name = key.removesuffix("_observation")
            storage_name = "page" if resource_name == "page_8" else resource_name
            failure_code = f"{resource_name}_get_failed"
            try:
                response = client.get(url, auth=auth)
            except httpx.HTTPError as exc:
                result[key] = _diagnostic(True, "authenticated_wordpress_rest", False, failure_code, f"Read-only GET failed: {exc.__class__.__name__}.", final_url=url)
                continue
            final_url = str(response.url)
            if response.status_code != 200:
                result[key] = _diagnostic(True, "authenticated_wordpress_rest", False, failure_code, f"Read-only GET returned HTTP {response.status_code}.", http_status=response.status_code, final_url=final_url)
                continue
            try:
                data = response.json()
            except ValueError:
                result[key] = _diagnostic(True, "authenticated_wordpress_rest", False, f"{resource_name}_invalid_json", "Read-only GET returned invalid JSON.", http_status=200, final_url=final_url)
                continue
            result[storage_name] = data
            result[key] = _diagnostic(True, "authenticated_wordpress_rest", True, None, "Read-only GET succeeded.", http_status=200, final_url=final_url)

        try:
            rendered_response = client.get(EXPECTED_URL)
        except httpx.HTTPError as exc:
            result["rendered_page_observation"] = _diagnostic(True, "credential_free_public_get", False, "rendered_public_network_failed", f"Public rendered GET failed: {exc.__class__.__name__}.", final_url=EXPECTED_URL)
        else:
            authenticated_observations_passed = all(
                isinstance(result.get(key), WordPressHeadingCorrectionObservationResult)
                and result[key].success
                for key in urls
            )
            result.update(
                _rendered_observation(
                    rendered_response,
                    manual_evidence,
                    authenticated_observations_passed=authenticated_observations_passed,
                )
            )

    page = result.get("page")
    media31 = result.get("media_31")
    media32 = result.get("media_32")
    rendered = result.get("rendered_snapshot")
    diagnostics = [result.get(key) for key in (*urls, "rendered_page_observation")]
    if all(isinstance(item, WordPressHeadingCorrectionObservationResult) and item.success for item in diagnostics) and all(isinstance(item, dict) for item in (page, media31, media32, rendered)):
        result["snapshot"] = {
            "page": _page_snapshot(page),
            "media_31": _media_snapshot(media31),
            "media_32": _media_snapshot(media32),
            "rendered": rendered,
        }
    return result


def _rendered_observation(
    response: httpx.Response,
    manual_evidence: Any | None,
    *,
    authenticated_observations_passed: bool,
) -> dict[str, Any]:
    final_url = str(response.url)
    status = response.status_code
    if final_url != EXPECTED_URL or bool(response.history):
        return {"rendered_page_observation": _diagnostic(True, "credential_free_public_get", False, "rendered_wrong_final_url", "Public rendered GET changed URL or redirected.", http_status=status, final_url=final_url)}
    body_and_headers = response.text + " " + " ".join(response.headers.values())
    if status == 403:
        if not authenticated_observations_passed:
            return {
                "rendered_page_observation": _diagnostic(
                    True,
                    "credential_free_public_get",
                    False,
                    "rendered_evidence_dependencies_failed",
                    "Signed browser evidence cannot replace a failed authenticated page or media observation.",
                    http_status=403,
                    final_url=final_url,
                )
            }
        evidence = manual_evidence.model_dump(mode="json", exclude_none=True) if hasattr(manual_evidence, "model_dump") else manual_evidence
        if evidence is None:
            return {"rendered_page_observation": _diagnostic(True, "credential_free_public_get", False, "rendered_public_forbidden", "Public rendered GET returned HTTP 403; valid signed schema-v2 evidence is required.", http_status=403, final_url=final_url)}
        valid, reason = validate_manual_browser_evidence(evidence, os.getenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", ""))
        if not valid or evidence.get("evidence_schema_version") != 2:
            return {"rendered_page_observation": _diagnostic(True, "signed_browser_evidence_after_public_403", False, "rendered_evidence_invalid", reason if not valid else "Signed schema-v2 duplicate-H1 evidence is required.", http_status=403, final_url=final_url)}
        snapshot = _rendered_snapshot_from_evidence(evidence)
        return {
            "rendered_page_observation": _diagnostic(True, "signed_browser_evidence_after_public_403", True, None, "Public rendered GET returned HTTP 403; independently signed schema-v2 browser evidence verified.", http_status=403, final_url=final_url),
            "rendered_h1_inventory": snapshot["h1_inventory"],
            "rendered_snapshot": snapshot,
        }
    if status != 200:
        return {"rendered_page_observation": _diagnostic(True, "credential_free_public_get", False, "rendered_public_get_failed", f"Public rendered GET returned HTTP {status}.", http_status=status, final_url=final_url)}
    if BOT_PATTERN.search(body_and_headers):
        return {"rendered_page_observation": _diagnostic(True, "credential_free_public_get", False, "rendered_challenge_page", "Public rendered GET returned a challenge-like document.", http_status=200, final_url=final_url)}
    snapshot = _rendered_snapshot(response.text, dict(response.headers))
    return {
        "rendered_page_observation": _diagnostic(True, "credential_free_public_get", True, None, "Public rendered GET succeeded.", http_status=200, final_url=final_url),
        "rendered_html": response.text,
        "rendered_snapshot": snapshot,
    }


def _rendered_snapshot_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    identity = evidence["page_identity"]
    absence = evidence["absence_findings"]
    inventory = evidence["h1_inventory"]
    return {
        "h1_texts": [item["text"] for item in inventory],
        "h1_inventory": inventory,
        "canonical": identity["canonical_url"],
        "document_title": identity["document_title"],
        "featured_image_url": identity["featured_image_url"],
        "featured_image_alt": identity["featured_image_alt"],
        "visible_text": evidence["normalized_visible_content"],
        "media_31_visible": True,
        "media_32_visible": not absence["media32_absent"],
        "metadata_count": 0,
        "head_hash": evidence["rendered_head_hash"],
        "visible_hash": evidence["visible_content_hash"],
        "signature_validated": True,
        "evidence_schema": evidence["evidence_schema"],
        "evidence_schema_version": 2,
        "evidence_id": evidence["evidence_id"],
        "cache_headers": {},
    }


def _verify_corrected_observation(
    observation: dict[str, Any],
    pre_snapshot: dict[str, Any] | None,
    audit_id: int | None,
) -> WordPressHeadingCorrectionVerification:
    snapshot = observation.get("snapshot") or {"page": {}, "media_31": {}, "media_32": {}, "rendered": {}}
    page = snapshot["page"]
    rendered = snapshot["rendered"]
    h1 = rendered.get("h1_texts", [])
    pre_page = (pre_snapshot or {}).get("page", {})
    invariant_fields = ("title", "slug", "link", "status", "excerpt", "featured_media")
    gates = [
        _gate("read_only_observation", "Read-only post-correction observation succeeded", "_error" not in observation, str(observation.get("_error", "Observation failed."))),
        _gate("body_hash", "Body hash matches the locked proposed hash", page.get("body_hash") == EXPECTED_PROPOSED_BODY_HASH, "Corrected body hash mismatch."),
        _gate("body_h2_prefix", "Body begins with the exact locked H2", page.get("body", "").startswith(PROPOSED_HEADING_FRAGMENT), "Body does not begin with the locked H2."),
        _gate("one_h1", "Rendered page contains exactly one H1", h1 == [EXPECTED_RENDERED_H1], "Rendered page must contain exactly the theme-owned H1."),
        _gate("wording_preserved", "Visible body heading wording is unchanged", "Drywood Termite Tenting in Orlando, Florida" in rendered.get("visible_text", ""), "Body heading wording changed."),
        _gate("page_invariants", "Title, canonical target, slug, URL, status, excerpt, and featured media are unchanged", bool(pre_page) and all(page.get(field) == pre_page.get(field) for field in invariant_fields), "A protected page field changed."),
        _gate("canonical", "Canonical URL remains exact", rendered.get("canonical") == EXPECTED_URL, "Canonical URL changed."),
        _gate("media_31", "Media 31 remains unchanged and visible", bool(pre_snapshot) and snapshot.get("media_31") == pre_snapshot.get("media_31") and rendered.get("media_31_visible") is True, "Media 31 changed or is not visible."),
        _gate("media_32", "Media 32 remains unchanged and absent from rendered HTML", bool(pre_snapshot) and snapshot.get("media_32") == pre_snapshot.get("media_32") and rendered.get("media_32_visible") is False, "Media 32 changed or appeared."),
        _gate("metadata_absent", "No meta description, Open Graph, Twitter, JSON-LD, or Atlas marker was added", rendered.get("metadata_count") == 0, "Unexpected metadata was rendered."),
        _gate("no_cache_purge", "No cache purge request exists in this workflow", True, "Cache purge is prohibited."),
    ]
    verified = all(gate.passed for gate in gates)
    return WordPressHeadingCorrectionVerification(
        status="verified" if verified else "blocked",
        verified=verified,
        audit_id=audit_id,
        body_hash=str(page.get("body_hash", "")),
        rendered_h1_count=len(h1),
        rendered_h1_text=h1[0] if len(h1) == 1 else None,
        gate_results=gates,
        snapshot=snapshot,
    )


def _page_snapshot(page: dict[str, Any]) -> dict[str, Any]:
    body = _text(page.get("content"))
    return {
        "id": page.get("id"),
        "title": _text(page.get("title")),
        "slug": page.get("slug"),
        "link": page.get("link"),
        "status": page.get("status"),
        "excerpt": _text(page.get("excerpt")),
        "featured_media": page.get("featured_media"),
        "body": body,
        "body_hash": wordpress_body_hash(body),
    }


def _media_snapshot(media: dict[str, Any]) -> dict[str, Any]:
    if "status_code" in media:
        return {"status_code": media["status_code"]}
    return {key: media.get(key) for key in ("id", "status", "slug", "source_url", "alt_text", "modified_gmt", "post")}


def _rendered_snapshot(html: str, headers: dict[str, str]) -> dict[str, Any]:
    lower = html.lower()
    headings = _headings(html)
    h1_inventory = [
        {
            **item,
            "ordinal": index + 1,
            "visible": True,
            "source_classification": (
                "theme_owned_post_title"
                if item.get("text") == EXPECTED_RENDERED_H1 and "wp-block-post-title" in item.get("classes", [])
                else "atlas_body_content"
                if item.get("text") == "Drywood Termite Tenting in Orlando, Florida" and {"entry-content", "wp-block-post-content"} & set(item.get("ancestor_classes", []))
                else "unclassified"
            ),
        }
        for index, item in enumerate(headings)
    ]
    canonical_match = re.search(r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']([^"\']+)', html, re.I)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    image_match = re.search(
        rf'<img[^>]+src=["\']{re.escape(EXPECTED_MEDIA_URL)}["\'][^>]*>',
        html,
        re.I,
    )
    image_alt_match = re.search(r'alt=["\']([^"\']*)', image_match.group(0), re.I) if image_match else None
    metadata_count = len(re.findall(r'<meta[^>]+(?:name|property)=["\'](?:description|og:|twitter:|atlas:)', html, re.I))
    metadata_count += len(re.findall(r'<script[^>]+type=["\']application/ld\+json["\']', html, re.I))
    visible = re.sub(r"<[^>]+>", " ", html)
    return {
        "h1_texts": [item.get("text") for item in headings],
        "h1_inventory": h1_inventory,
        "canonical": canonical_match.group(1) if canonical_match else None,
        "document_title": re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else None,
        "featured_image_url": EXPECTED_MEDIA_URL if image_match else None,
        "featured_image_alt": image_alt_match.group(1) if image_alt_match else None,
        "visible_text": " ".join(visible.split()),
        "media_31_visible": "orlando-drywood-termite-tenting-hero.png" in lower,
        "media_32_visible": "/wp-content/uploads/" in lower and bool(re.search(r'(?:attachment-|wp-image-)32\b|media.?32', lower)),
        "metadata_count": metadata_count,
        "cache_headers": {key.lower(): value for key, value in headers.items() if key.lower() in {"age", "cache-control", "cf-cache-status", "x-cache", "x-proxy-cache"}},
    }


def _release_identity() -> tuple[dict[str, Any] | None, str | None]:
    try:
        return verify_runtime_release_identity(resolve_program_root()).identity(), None
    except DeploymentReleaseError as exc:
        return None, str(exc)


def _backups_are_fresh(backups: WordPressHeadingCorrectionBackupIdentities) -> bool:
    now = datetime.now(UTC)
    for value in backups.model_dump().values():
        match = re.search(r"(\d{4}-\d{2}-\d{2})-(\d{6})", value)
        if not match:
            return False
        created = datetime.strptime("".join(match.groups()), "%Y-%m-%d%H%M%S").replace(tzinfo=UTC)
        if created > now + timedelta(minutes=5) or now - created > BACKUP_MAX_AGE:
            return False
    return True


def _sign(body: dict[str, Any]) -> str:
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    signature = _encode(hmac.new(_token_secret, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def _store_token_handle(
    raw_token: str,
    token_body: dict[str, Any],
    *,
    issued_at: datetime,
    expires_at: datetime,
    manual_browser_evidence: dict[str, Any] | None,
) -> str:
    entry = _TokenHandleEntry(
        raw_token=raw_token,
        action=str(token_body.get("action", "")),
        atlas_page_id=int(token_body.get("atlas_page_id", 0)),
        wordpress_post_id=int(token_body.get("wordpress_post_id", 0)),
        issued_at=issued_at,
        expires_at=expires_at,
        proposed_body_hash=str(token_body.get("proposed_body_hash", "")),
        backup_digest=str(token_body.get("backup_digest", "")),
        release_digest=str(token_body.get("release_digest", "")),
        manual_browser_evidence=manual_browser_evidence,
    )
    with _token_handle_lock:
        _purge_expired_token_handles(issued_at)
        handle = secrets.token_urlsafe(32)
        while handle in _token_handles:
            handle = secrets.token_urlsafe(32)
        _token_handles[handle] = entry
        timer = Timer(max(0.0, (expires_at - issued_at).total_seconds()), _expire_token_handle, args=(handle,))
        timer.daemon = True
        _token_handle_timers[handle] = timer
    timer.start()
    return handle


def _consume_token_handle(
    handle: str,
    page_id: int,
    backups: WordPressHeadingCorrectionBackupIdentities,
) -> tuple[str, _ConsumedTokenContext]:
    now = datetime.now(UTC)
    with _token_handle_lock:
        entry = _token_handles.pop(handle, None)
        timer = _token_handle_timers.pop(handle, None)
        if timer is not None:
            timer.cancel()
        _purge_expired_token_handles(now)
    if entry is None:
        raise HTTPException(422, "The heading-correction token handle is unknown, expired, already consumed, or cleared by a backend restart.")
    if entry.expires_at <= now:
        raise HTTPException(422, "The heading-correction token handle expired.")
    if (
        entry.action != TOKEN_ACTION
        or entry.atlas_page_id != page_id
        or entry.wordpress_post_id != WORDPRESS_POST_ID
        or entry.proposed_body_hash != EXPECTED_PROPOSED_BODY_HASH
    ):
        raise HTTPException(422, "The heading-correction token handle does not match the locked target or action.")
    if entry.backup_digest != _digest(backups.model_dump(mode="json")):
        raise HTTPException(409, "The Atlas backup identities changed after dry run.")
    return entry.raw_token, _ConsumedTokenContext(
        action=entry.action,
        atlas_page_id=entry.atlas_page_id,
        wordpress_post_id=entry.wordpress_post_id,
        proposed_body_hash=entry.proposed_body_hash,
        backup_digest=entry.backup_digest,
        release_digest=entry.release_digest,
        manual_browser_evidence=entry.manual_browser_evidence,
    )


def _purge_expired_token_handles(now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    expired = [handle for handle, entry in _token_handles.items() if entry.expires_at <= current]
    for handle in expired:
        _token_handles.pop(handle, None)
        timer = _token_handle_timers.pop(handle, None)
        if timer is not None:
            timer.cancel()


def _expire_token_handle(handle: str) -> None:
    with _token_handle_lock:
        _token_handles.pop(handle, None)
        _token_handle_timers.pop(handle, None)


def _clear_token_handles() -> None:
    """Model a backend restart in tests; production restarts clear module memory."""
    with _token_handle_lock:
        _token_handles.clear()
        for timer in _token_handle_timers.values():
            timer.cancel()
        _token_handle_timers.clear()


def _verify_token(value: str, page_id: int) -> dict[str, Any]:
    try:
        encoded, supplied = value.split(".", 1)
        expected = _encode(hmac.new(_token_secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected):
            raise ValueError
        body = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(422, "The heading-correction token is invalid.")
    if body.get("action") != TOKEN_ACTION or body.get("atlas_page_id") != page_id or body.get("wordpress_post_id") != WORDPRESS_POST_ID:
        raise HTTPException(422, "The heading-correction token does not match the locked target.")
    if int(body.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()):
        raise HTTPException(422, "The heading-correction token expired.")
    return body


def _mark_reconciliation_required(session: Session, audit: WordPressHeadingCorrectionAudit, message: str, writes: int) -> None:
    audit.wordpress_write_count = writes
    _finish_audit(session, audit, "reconciliation_required", message)


def _finish_audit(session: Session, audit: WordPressHeadingCorrectionAudit, status: str, message: str) -> None:
    audit.status = status
    audit.completed_at = datetime.now(UTC)
    audit.error_message = message
    session.add(audit)
    session.commit()


def _recover_partial_finalization(session: Session, audit_id: int, snapshot: dict[str, Any] | None) -> None:
    try:
        persisted = session.get(WordPressHeadingCorrectionAudit, audit_id)
        if persisted:
            persisted.status = "reconciliation_required"
            persisted.wordpress_write_count = 1
            persisted.post_snapshot = snapshot
            persisted.error_message = "WordPress correction succeeded but Atlas finalization failed."
            session.add(persisted)
            session.commit()
    except Exception:
        session.rollback()


def _target(page_id: int) -> None:
    if page_id != ATLAS_PAGE_ID:
        raise HTTPException(404, "The guarded heading correction exists only for Atlas page 41.")


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("raw", "rendered"):
            if isinstance(value.get(key), str):
                return value[key]
    return ""


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _diagnostic(
    attempted: bool,
    acquisition_source: str,
    success: bool,
    failure_code: str | None,
    message: str,
    *,
    http_status: int | None = None,
    final_url: str | None = None,
) -> WordPressHeadingCorrectionObservationResult:
    return WordPressHeadingCorrectionObservationResult(
        attempted=attempted,
        acquisition_source=acquisition_source,
        http_status=http_status,
        final_url=final_url,
        success=success,
        failure_code=failure_code,
        message=message,
    )


def _observation_diagnostic(
    observation: dict[str, Any],
    key: str,
    legacy_success: bool,
) -> WordPressHeadingCorrectionObservationResult:
    value = observation.get(key)
    if isinstance(value, WordPressHeadingCorrectionObservationResult):
        return value
    if isinstance(value, dict):
        return WordPressHeadingCorrectionObservationResult.model_validate(value)
    return _diagnostic(
        attempted=legacy_success,
        acquisition_source="mocked_read_only_observation" if legacy_success else "unavailable",
        success=legacy_success,
        failure_code=None if legacy_success else key.replace("_observation", "_missing"),
        message="Read-only observation succeeded." if legacy_success else "Read-only observation is unavailable.",
    )


def _observation_gate(
    code: str,
    label: str,
    diagnostic: WordPressHeadingCorrectionObservationResult,
) -> WordPressDraftGateResult:
    failure = diagnostic.failure_code or diagnostic.message
    return _gate(code, label, diagnostic.success, failure)


def _gate(code: str, label: str, passed: bool, failure: str) -> WordPressDraftGateResult:
    return WordPressDraftGateResult(code=code, label=label, passed=bool(passed), message="Passed." if passed else failure)


def _dump_gates(gates: list[WordPressDraftGateResult]) -> list[dict[str, Any]]:
    return [gate.model_dump(mode="json") for gate in gates]
