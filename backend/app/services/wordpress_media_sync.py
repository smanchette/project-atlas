from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import mimetypes
from pathlib import Path
import re
import secrets
from urllib.parse import quote, urljoin, urlparse

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import GeneratedPage, ImageMetadata, PageImageAssignment, WordPressMediaSyncAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult, WordPressMediaAttachmentMatch, WordPressMediaDryRun,
    WordPressMediaInspectionCandidate, WordPressMediaInspectionResult,
    WordPressMediaReconciliationApplyRequest, WordPressMediaReconciliationApplyResult,
    WordPressMediaFeaturedReference, WordPressMediaReconciliationCandidate,
    WordPressMediaReconciliationDryRun,
    WordPressFeaturedImageApplyRequest, WordPressFeaturedImageApplyResult,
    WordPressFeaturedImageDryRun,
    WordPressMediaUploadRequest, WordPressMediaUploadResult,
)
from app.services.wordpress_draft_review import check_live_wordpress_draft_status
from app.services.wordpress_sandbox import get_wordpress_application_password, read_wordpress_settings

TARGET_PAGE_ID = 41
TARGET_POST_ID = 8
TARGET_IMAGE_ID = 1
TARGET_ASSIGNMENT_ID = 1
TOKEN_TTL_MINUTES = 15
UPLOAD_PHRASE = "UPLOAD ORLANDO HERO IMAGE"
RECONCILIATION_PHRASE = "RECONCILE ORLANDO HERO MEDIA"
FEATURED_IMAGE_PHRASE = "SET ORLANDO HERO AS FEATURED IMAGE"
CANDIDATE_MEDIA_IDS = (31, 32)
EXPECTED_SLUG = "drywood-termite-tenting-orlando-fl"
EXPECTED_ORLANDO_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
EXPECTED_CHECKSUM = "9f94d1ba555c2f3655bd600a61aac3247ab2a1a951a6cf73b1152d94fe40b2a0"
ALLOWED_MIME = {"image/png": "PNG", "image/jpeg": "JPEG"}
_secret = secrets.token_bytes(32)


def dry_run_wordpress_media(session: Session, page_id: int) -> WordPressMediaDryRun:
    if page_id != TARGET_PAGE_ID:
        raise HTTPException(status_code=404, detail="The v0.49 media flow is limited to Orlando page 41.")
    page = session.get(GeneratedPage, page_id)
    assignment = session.get(PageImageAssignment, TARGET_ASSIGNMENT_ID)
    image = session.get(ImageMetadata, TARGET_IMAGE_ID)
    if not page or not assignment or not image:
        raise HTTPException(status_code=404, detail="The Orlando hero media mapping is incomplete.")

    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    gates: list[WordPressDraftGateResult] = []
    gates += [
        _gate("orlando_only", "Orlando page 41 only", page.id == 41, "Only Orlando page 41 is allowed."),
        _gate("post_id", "Saved WordPress post is 8", page.wordpress_post_id == 8, "Orlando must map to WordPress post 8."),
        _gate("page_published", "Atlas page is published", page.status == "published" and page.wordpress_status == "publish", "Orlando must remain published."),
        _gate("assignment", "Hero assignment is exact", assignment.id == 1 and assignment.generated_page_id == 41 and assignment.image_metadata_id == 1 and assignment.image_role == "hero" and assignment.status == "active", "Assignment 1 must be the active hero for page 41 and image 1."),
        _gate("image_reviewed", "Image metadata is reviewed", image.review_status == "reviewed", "Image 1 must be reviewed."),
        _gate("credentials", "WordPress credentials are available", bool(settings.site_url and settings.username and password and settings.publishing_mode == "sandbox"), "Sandbox mode and process-memory credentials are required."),
    ]
    alt_text = (assignment.override_alt_text or image.reviewed_alt_text or "").strip()
    gates.append(_gate("reviewed_alt", "Reviewed alt text exists", bool(alt_text), "Reviewed alt text is required."))

    path, path_error = _resolve_media_path(image)
    gates.append(_gate("local_path", "Local file resolves inside an approved media root", path is not None, path_error or "Local media path is invalid."))
    file_name = path.name if path else Path(image.asset_url or image.file_name).name
    mime_type, size, width, height, checksum = "application/octet-stream", 0, 0, 0, ""
    if path:
        mime_type, size, width, height, checksum, validation_error = _inspect_file(path)
        gates.append(_gate("file_valid", "Image file is valid", validation_error is None, validation_error or "Image file is invalid."))
    else:
        gates.append(_gate("file_valid", "Image file is valid", False, "Image file could not be inspected."))
    live = check_live_wordpress_draft_status(session, page_id)
    gates += [
        _gate("live_get", "Live WordPress GET succeeds", not live.error_message, live.error_message or "Live GET failed."),
        _gate("live_publish", "Post 8 remains published", live.wordpress_post_id == 8 and live.wordpress_status == "publish", "Live WordPress post 8 must remain published."),
        _gate("no_derivatives", "No derivative generation requested", True, "Derivative generation is unavailable."),
        _gate("no_content_change", "No post or featured-image change requested", True, "Content and featured-image changes are unavailable."),
        _gate("one_image", "Exactly one image", True, "Bulk media is unavailable."),
    ]
    match = _attachment_match(settings.site_url, settings.username, password, image, checksum) if password and checksum else WordPressMediaAttachmentMatch(status="unavailable", message="Attachment lookup unavailable until credentials and a valid checksum are present.")
    gates.append(_gate("attachment_search", "Existing attachment state is safe", match.status in {"missing", "matched"}, match.message))
    gates.append(_not_already_mapped_gate(image, match))

    ready = all(g.passed for g in gates)
    token = phrase = expires_at = None
    if ready:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign(page_id, checksum, expires)
        phrase = UPLOAD_PHRASE
        expires_at = expires.isoformat()
    return WordPressMediaDryRun(
        page_id=41, wordpress_post_id=8, assignment_id=1, image_id=1,
        status="dry_run_ready" if ready else "blocked", ready=ready,
        resolved_local_path=str(path) if path else "", source_file_name=file_name,
        original_filename=image.original_filename, mime_type=mime_type, file_size=size,
        width=width, height=height, checksum=checksum, alt_text=alt_text,
        image_title=image.image_title or image.file_name,
        existing_wordpress_media_id=image.wordpress_media_id,
        existing_wordpress_media_url=image.wordpress_media_url,
        attachment_match=match, gate_results=gates, confirmation_token=token,
        confirmation_phrase=phrase, expires_at=expires_at,
    )


def upload_wordpress_media(session: Session, page_id: int, request: WordPressMediaUploadRequest) -> WordPressMediaUploadResult:
    token = _verify(request.confirmation_token, page_id)
    dry = dry_run_wordpress_media(session, page_id)
    if not hmac.compare_digest(request.confirmation_phrase, UPLOAD_PHRASE):
        raise HTTPException(status_code=422, detail="The media upload confirmation phrase is incorrect.")
    if token["checksum"] != dry.checksum or not dry.ready:
        raise HTTPException(status_code=409, detail="Media state changed or a dry-run gate is blocked. Run a new dry run.")
    backup_gate = _backup_gate(request.confirmed_backup_file)
    gates = [*dry.gate_results, backup_gate]
    if not backup_gate.passed:
        raise HTTPException(status_code=409, detail={"message": "Media upload is blocked.", "gate_results": [g.model_dump(mode="json") for g in gates]})

    page = session.get(GeneratedPage, 41)
    image = session.get(ImageMetadata, 1)
    path = Path(dry.resolved_local_path)
    current = hashlib.sha256(path.read_bytes()).hexdigest()
    if current != dry.checksum:
        raise HTTPException(status_code=409, detail="The image checksum changed after dry run.")
    settings = read_wordpress_settings(session)
    audit = WordPressMediaSyncAudit(
        generated_page_id=41, image_metadata_id=1, page_image_assignment_id=1,
        wordpress_post_id=8, action_type="upload_media", status="pending",
        wordpress_site_url=settings.site_url, source_file_name=dry.source_file_name,
        source_mime_type=dry.mime_type, source_file_size=dry.file_size,
        source_width=dry.width, source_height=dry.height, source_checksum=dry.checksum,
        alt_text=dry.alt_text, gate_results=[g.model_dump(mode="json") for g in gates],
        backup_file_name=request.confirmed_backup_file,
    )
    session.add(audit); session.commit(); session.refresh(audit)
    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/media"
    password = get_wordpress_application_password() or ""
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.post(endpoint, files={"file": (dry.source_file_name, path.read_bytes(), dry.mime_type)}, auth=httpx.BasicAuth(settings.username, password))
            if response.status_code not in {200, 201}: raise RuntimeError(f"WordPress returned HTTP {response.status_code}.")
            data = response.json()
            media_id = data.get("id")
            if not isinstance(media_id, int): raise RuntimeError("WordPress did not return a media ID.")
            audit.wordpress_media_id = media_id
            audit.returned_media_url = data.get("source_url") if isinstance(data.get("source_url"), str) else None
            session.add(audit); session.commit(); session.refresh(audit)
            markers = {"_atlas_source_checksum": dry.checksum, "_atlas_image_metadata_id": "1", "_atlas_generated_page_id": "41", "_atlas_managed_media": "true"}
            patched = client.post(f"{endpoint}/{media_id}", json={"alt_text": dry.alt_text, "title": dry.image_title, "meta": markers}, auth=httpx.BasicAuth(settings.username, password))
            if patched.status_code not in {200, 201}: raise RuntimeError(f"WordPress metadata update returned HTTP {patched.status_code}.")
            verified = client.get(f"{endpoint}/{media_id}?context=edit", auth=httpx.BasicAuth(settings.username, password))
            if verified.status_code >= 400: raise RuntimeError(f"WordPress attachment verification GET returned HTTP {verified.status_code}.")
            verify_data = verified.json()
            media_url = verify_data.get("source_url")
            mismatches = _verification_mismatches(
                verify_data, media_id=media_id, expected_url=None,
                mime_type=dry.mime_type, alt_text=dry.alt_text, checksum=dry.checksum,
            )
            if mismatches:
                raise RuntimeError("WordPress attachment verification failed: " + "; ".join(mismatches))
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        audit.status = "failed"; audit.completed_at = datetime.now(UTC); audit.error_message = str(exc)
        session.add(audit); session.commit()
        raise HTTPException(status_code=502, detail="WordPress media upload or verification failed.") from exc
    now = datetime.now(UTC)
    try:
        image.wordpress_media_id = media_id; image.wordpress_media_url = media_url
        image.wordpress_media_status = "uploaded"; image.wordpress_media_checksum = dry.checksum
        image.wordpress_media_uploaded_at = now; image.last_wordpress_media_sync_at = now; image.updated_at = now
        audit.wordpress_media_id = media_id; audit.returned_media_url = media_url; audit.status = "uploaded"; audit.completed_at = now
        session.add(image); session.add(audit); session.commit()
    except Exception as exc:
        session.rollback()
        try:
            persisted = session.get(WordPressMediaSyncAudit, audit.id)
            if persisted:
                persisted.status = "reconciliation_required"; persisted.wordpress_media_id = media_id; persisted.returned_media_url = media_url; persisted.error_message = "WordPress upload succeeded but Atlas mapping failed."
                session.add(persisted); session.commit()
        except Exception: session.rollback()
        raise HTTPException(status_code=500, detail="WordPress media uploaded, but Atlas requires manual reconciliation.") from exc
    return WordPressMediaUploadResult(page_id=41, wordpress_post_id=8, image_id=1, assignment_id=1, status="uploaded", wordpress_media_id=media_id, wordpress_media_url=media_url, checksum=dry.checksum, alt_text=dry.alt_text, audit_id=audit.id or 0, gate_results=gates)


def inspect_wordpress_media(session: Session, page_id: int) -> WordPressMediaInspectionResult:
    if page_id != TARGET_PAGE_ID:
        raise HTTPException(status_code=404, detail="The media inspector is limited to Orlando page 41.")
    image = session.get(ImageMetadata, TARGET_IMAGE_ID)
    assignment = session.get(PageImageAssignment, TARGET_ASSIGNMENT_ID)
    if not image or not assignment:
        raise HTTPException(status_code=404, detail="The Orlando hero media mapping is incomplete.")
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if not settings.site_url or not settings.username or not password:
        raise HTTPException(status_code=409, detail="WordPress credentials are not available in backend process memory.")
    path, path_error = _resolve_media_path(image)
    if not path:
        raise HTTPException(status_code=409, detail=path_error or "The Orlando hero file is unavailable.")
    mime_type, _, _, _, checksum, file_error = _inspect_file(path)
    if file_error:
        raise HTTPException(status_code=409, detail=file_error)
    alt_text = (assignment.override_alt_text or image.reviewed_alt_text or "").strip()
    title = image.image_title or image.file_name
    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/media"
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(
                f"{endpoint}?context=edit&per_page=50&orderby=date&order=desc",
                auth=httpx.BasicAuth(settings.username, password),
            )
        if response.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"WordPress recent-media inspection returned HTTP {response.status_code}.")
        records = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="WordPress recent-media inspection failed.") from exc
    if not isinstance(records, list):
        raise HTTPException(status_code=502, detail="WordPress recent-media inspection returned invalid JSON.")
    candidates: list[WordPressMediaInspectionCandidate] = []
    target_stem = path.stem.lower()
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), int):
            continue
        source_url = record.get("source_url") if isinstance(record.get("source_url"), str) else None
        media_file = (record.get("media_details") or {}).get("file")
        record_title = _wp_text(record.get("title"))
        record_alt = record.get("alt_text") if isinstance(record.get("alt_text"), str) else None
        slug = record.get("slug") if isinstance(record.get("slug"), str) else None
        likely = any((
            target_stem in (source_url or "").lower(),
            target_stem in str(media_file or "").lower(),
            target_stem in (slug or "").lower(),
            record_title == title,
            record_alt == alt_text,
        ))
        if not likely:
            continue
        meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
        atlas_meta = {key: meta.get(key) for key in (
            "_atlas_source_checksum", "_atlas_image_metadata_id",
            "_atlas_generated_page_id", "_atlas_managed_media",
        ) if key in meta}
        candidates.append(WordPressMediaInspectionCandidate(
            wordpress_media_id=record["id"], date_gmt=record.get("date_gmt"),
            modified_gmt=record.get("modified_gmt"), source_url=source_url,
            mime_type=record.get("mime_type"), slug=slug, title=record_title,
            alt_text=record_alt, media_file=media_file, atlas_meta=atlas_meta,
            likely_target=True,
            verification_mismatches=_verification_mismatches(
                record, media_id=record["id"], expected_url=None,
                mime_type=mime_type, alt_text=alt_text, checksum=checksum,
            ),
        ))
    return WordPressMediaInspectionResult(
        page_id=41, wordpress_post_id=8, image_id=1, source_file_name=path.name,
        expected_title=title, expected_alt_text=alt_text,
        expected_mime_type=mime_type, expected_checksum=checksum,
        candidate_count=len(candidates), possible_duplicate_count=max(0, len(candidates) - 1),
        candidates=candidates,
    )


def _verification_mismatches(
    data: dict, *, media_id: int, expected_url: str | None,
    mime_type: str, alt_text: str, checksum: str,
) -> list[str]:
    mismatches: list[str] = []
    if data.get("id") != media_id:
        mismatches.append(f"media_id expected {media_id!r}, got {data.get('id')!r}")
    if data.get("alt_text") != alt_text:
        mismatches.append(f"alt_text expected {alt_text!r}, got {data.get('alt_text')!r}")
    if data.get("mime_type") != mime_type:
        mismatches.append(f"mime_type expected {mime_type!r}, got {data.get('mime_type')!r}")
    source_url = data.get("source_url")
    if not isinstance(source_url, str) or not source_url:
        mismatches.append(f"source_url expected a non-empty string, got {source_url!r}")
    elif expected_url is not None and source_url != expected_url:
        mismatches.append(f"source_url expected {expected_url!r}, got {source_url!r}")
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    expected_meta = {
        "_atlas_source_checksum": checksum,
        "_atlas_image_metadata_id": "1",
        "_atlas_generated_page_id": "41",
        "_atlas_managed_media": "true",
    }
    for key, expected in expected_meta.items():
        if str(meta.get(key)) != expected:
            mismatches.append(f"meta.{key} expected {expected!r}, got {meta.get(key)!r}")
    return mismatches


def _wp_text(value: object) -> str | None:
    if isinstance(value, dict):
        raw = value.get("raw") or value.get("rendered")
        return raw if isinstance(raw, str) else None
    return value if isinstance(value, str) else None


def dry_run_wordpress_media_reconciliation(
    session: Session, page_id: int,
) -> WordPressMediaReconciliationDryRun:
    if page_id != TARGET_PAGE_ID:
        raise HTTPException(status_code=404, detail="Reconciliation is limited to Orlando page 41.")
    page = session.get(GeneratedPage, TARGET_PAGE_ID)
    image = session.get(ImageMetadata, TARGET_IMAGE_ID)
    assignment = session.get(PageImageAssignment, TARGET_ASSIGNMENT_ID)
    if not page or not image or not assignment:
        raise HTTPException(status_code=404, detail="The Orlando reconciliation target is incomplete.")
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    path, path_error = _resolve_media_path(image)
    local_mime, local_size, local_width, local_height, local_checksum, file_error = (
        _inspect_file(path) if path else ("application/octet-stream", 0, 0, 0, "", path_error)
    )
    gates = [
        _gate("fixed_target", "Fixed Orlando target", page.wordpress_post_id == 8 and assignment.generated_page_id == 41 and assignment.image_metadata_id == 1, "Page, post, image, or assignment target changed."),
        _gate("mapping_clear", "Atlas media mapping is empty", image.wordpress_media_id is None, "ImageMetadata 1 already has a WordPress media mapping."),
        _gate("local_file", "Local source file is valid", file_error is None and local_checksum != "", file_error or "Local source validation failed."),
        _gate("local_expected", "Local source matches expected Orlando asset", local_mime == "image/png" and local_size == 2_823_150 and local_width == 1672 and local_height == 941, "Local MIME, size, or dimensions changed."),
        _gate("credentials", "WordPress credentials are available", bool(settings.site_url and settings.username and password), "WordPress credentials are not available in backend memory."),
    ]
    candidates: list[WordPressMediaReconciliationCandidate] = []
    post_data: dict = {}
    if settings.site_url and settings.username and password:
        auth = httpx.BasicAuth(settings.username, password)
        api = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2"
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, read=30.0), follow_redirects=False) as client:
                post_response = client.get(f"{api}/pages/8?context=edit", auth=auth)
                if post_response.status_code >= 400:
                    raise RuntimeError(f"WordPress post inspection returned HTTP {post_response.status_code}.")
                post_data = post_response.json()
                for media_id in CANDIDATE_MEDIA_IDS:
                    candidates.append(_inspect_reconciliation_candidate(
                        client, api, auth, settings.site_url, media_id,
                        title=image.image_title or image.file_name,
                        alt_text=(assignment.override_alt_text or image.reviewed_alt_text or "").strip(),
                        checksum=local_checksum,
                    ))
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            gates.append(_gate("wordpress_inspection", "Authenticated WordPress inspection succeeds", False, str(exc)))
    post_status = post_data.get("status") if isinstance(post_data, dict) else None
    post_featured = post_data.get("featured_media") if isinstance(post_data, dict) else None
    gates += [
        _gate("post_identity", "WordPress post 8 identity matches", post_data.get("id") == 8 and post_data.get("slug") == EXPECTED_SLUG, "WordPress post ID or slug changed."),
        _gate("post_publish", "WordPress post 8 remains published", post_status == "publish", "WordPress post 8 is not publish."),
        _gate("post_featured_media", "WordPress post 8 has no featured image", post_featured == 0, "WordPress post 8 has an unexpected or unverifiable featured image."),
    ]
    selected, duplicates = _select_reconciliation_candidate(candidates)
    gates.append(_gate(
        "candidate_selection", "At least one verified candidate is selectable",
        selected is not None, _candidate_selection_failure(candidates),
    ))
    ready = all(g.passed for g in gates) and selected is not None
    token = phrase = expires_at = None
    if ready and selected:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign_reconciliation(local_checksum, candidates, selected.wordpress_media_id, duplicates, expires)
        phrase = RECONCILIATION_PHRASE
        expires_at = expires.isoformat()
    return WordPressMediaReconciliationDryRun(
        page_id=41, wordpress_post_id=8, image_id=1, assignment_id=1,
        candidate_ids=list(CANDIDATE_MEDIA_IDS), local_checksum=local_checksum,
        local_file_size=local_size, candidates=candidates,
        selected_media_id=selected.wordpress_media_id if selected else None,
        selected_media_url=selected.source_url if selected else None,
        duplicate_candidate_ids=duplicates, post_status=post_status,
        post_featured_media=post_featured, gate_results=gates,
        status="reconciliation_ready" if ready else "blocked", ready=ready,
        confirmation_token=token, confirmation_phrase=phrase, expires_at=expires_at,
    )


def reconcile_wordpress_media(
    session: Session, page_id: int, request: WordPressMediaReconciliationApplyRequest,
) -> WordPressMediaReconciliationApplyResult:
    token = _verify_reconciliation(request.confirmation_token, page_id)
    if not hmac.compare_digest(request.confirmation_phrase, RECONCILIATION_PHRASE):
        raise HTTPException(status_code=422, detail="The reconciliation confirmation phrase is incorrect.")
    dry = dry_run_wordpress_media_reconciliation(session, page_id)
    backup_gate = _backup_gate(request.confirmed_backup_file)
    gates = [*dry.gate_results, backup_gate]
    current_hashes = {str(c.wordpress_media_id): c.remote_checksum for c in dry.candidates}
    if (
        not dry.ready or not backup_gate.passed
        or token.get("checksum") != dry.local_checksum
        or token.get("candidate_ids") != dry.candidate_ids
        or token.get("selected_media_id") != dry.selected_media_id
        or token.get("duplicate_candidate_ids") != dry.duplicate_candidate_ids
        or token.get("remote_hashes") != current_hashes
    ):
        raise HTTPException(status_code=409, detail="Reconciliation state changed or a required gate is blocked. Run a new dry run.")
    selected = next((c for c in dry.candidates if c.wordpress_media_id == dry.selected_media_id), None)
    if not selected or not selected.source_url or not selected.date_gmt:
        raise HTTPException(status_code=409, detail="The selected attachment is incomplete.")
    settings = read_wordpress_settings(session)
    evidence = {
        "code": "reconciliation_evidence", "passed": True,
        "candidate_ids": dry.candidate_ids,
        "selected_media_id": dry.selected_media_id,
        "duplicate_candidate_ids": dry.duplicate_candidate_ids,
        "remote_hashes": current_hashes,
        "post_observation": {"id": 8, "status": dry.post_status, "featured_media": dry.post_featured_media},
    }
    audit = WordPressMediaSyncAudit(
        generated_page_id=41, image_metadata_id=1, page_image_assignment_id=1,
        wordpress_post_id=8, wordpress_media_id=selected.wordpress_media_id,
        action_type="reconcile_existing_media", status="pending",
        wordpress_site_url=settings.site_url, source_file_name=Path(selected.source_url).name,
        source_mime_type=selected.mime_type or "image/png",
        source_file_size=selected.file_size or dry.local_file_size,
        source_width=selected.width or 1672, source_height=selected.height or 941,
        source_checksum=dry.local_checksum,
        alt_text=selected.alt_text or "", returned_media_url=selected.source_url,
        gate_results=[g.model_dump(mode="json") for g in gates] + [evidence],
        backup_file_name=request.confirmed_backup_file,
    )
    session.add(audit); session.commit(); session.refresh(audit)
    image = session.get(ImageMetadata, 1)
    now = datetime.now(UTC)
    try:
        if not image or image.wordpress_media_id is not None:
            raise RuntimeError("ImageMetadata mapping changed before reconciliation commit.")
        uploaded_at = datetime.fromisoformat(selected.date_gmt.replace("Z", "+00:00"))
        image.wordpress_media_id = selected.wordpress_media_id
        image.wordpress_media_url = selected.source_url
        image.wordpress_media_status = "reconciled"
        image.wordpress_media_checksum = dry.local_checksum
        image.wordpress_media_uploaded_at = uploaded_at
        image.last_wordpress_media_sync_at = now
        image.updated_at = now
        audit.status = "reconciled"; audit.completed_at = now
        session.add(image); session.add(audit); session.commit()
    except Exception as exc:
        session.rollback()
        persisted = session.get(WordPressMediaSyncAudit, audit.id)
        if persisted:
            persisted.status = "failed"; persisted.completed_at = datetime.now(UTC); persisted.error_message = str(exc)
            session.add(persisted); session.commit()
        raise HTTPException(status_code=500, detail="Atlas media reconciliation failed without changing WordPress.") from exc
    return WordPressMediaReconciliationApplyResult(
        page_id=41, wordpress_post_id=8, image_id=1, assignment_id=1,
        status="reconciled", wordpress_media_id=selected.wordpress_media_id,
        wordpress_media_url=selected.source_url, checksum=dry.local_checksum,
        duplicate_candidate_ids=dry.duplicate_candidate_ids,
        audit_id=audit.id or 0, gate_results=gates,
    )


def dry_run_wordpress_featured_image(
    session: Session, page_id: int,
) -> WordPressFeaturedImageDryRun:
    if page_id != TARGET_PAGE_ID:
        raise HTTPException(status_code=404, detail="Featured-image sync is limited to Orlando page 41.")
    page = session.get(GeneratedPage, 41)
    image = session.get(ImageMetadata, 1)
    assignment = session.get(PageImageAssignment, 1)
    if not page or not image or not assignment:
        raise HTTPException(status_code=404, detail="The Orlando featured-image target is incomplete.")
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    path, path_error = _resolve_media_path(image)
    local_mime, local_size, local_width, local_height, local_checksum, file_error = (
        _inspect_file(path) if path else ("application/octet-stream", 0, 0, 0, "", path_error)
    )
    latest_reconciliation = session.exec(
        select(WordPressMediaSyncAudit).where(
            WordPressMediaSyncAudit.generated_page_id == 41,
            WordPressMediaSyncAudit.image_metadata_id == 1,
            WordPressMediaSyncAudit.action_type == "reconcile_existing_media",
            WordPressMediaSyncAudit.status == "reconciled",
            WordPressMediaSyncAudit.wordpress_media_id == 31,
        ).order_by(WordPressMediaSyncAudit.attempted_at.desc())
    ).first()
    gates = [
        _gate("fixed_target", "Fixed Orlando target", page.wordpress_post_id == 8 and assignment.generated_page_id == 41 and assignment.image_metadata_id == 1, "Page, post, image, or assignment target changed."),
        _gate("atlas_published", "Atlas Orlando page remains published", page.status == "published" and page.wordpress_status == "publish", "Atlas Orlando page or saved WordPress status changed."),
        _gate("media_mapping", "ImageMetadata 1 maps to media 31", image.wordpress_media_id == 31 and image.wordpress_media_status == "reconciled", "The reconciled WordPress media mapping is missing or changed."),
        _gate("mapping_checksum", "Mapped checksum matches Atlas", image.wordpress_media_checksum == EXPECTED_CHECKSUM and local_checksum == EXPECTED_CHECKSUM, "The mapped or local checksum changed."),
        _gate("local_source", "Local Orlando source remains exact", file_error is None and local_mime == "image/png" and local_size == 2_823_150 and local_width == 1672 and local_height == 941, file_error or "The local source MIME, size, or dimensions changed."),
        _gate("reconciliation_audit", "Successful reconciliation audit exists", latest_reconciliation is not None, "No successful reconciliation audit for media 31 exists."),
        _gate("credentials", "WordPress credentials are available", bool(settings.site_url and settings.username and password), "WordPress credentials are not available in backend memory."),
        _gate("duplicate_excluded", "Duplicate media 32 is excluded", True, "Duplicate media 32 must remain excluded."),
        _gate("planned_payload", "Planned payload contains featured_media only", True, "Featured-image payload shape is unsafe."),
    ]
    post_data: dict = {}
    media: WordPressMediaReconciliationCandidate | None = None
    if settings.site_url and settings.username and password and local_checksum:
        auth = httpx.BasicAuth(settings.username, password)
        api = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2"
        try:
            with httpx.Client(timeout=httpx.Timeout(20.0, read=30.0), follow_redirects=False) as client:
                post_response = client.get(f"{api}/pages/8?context=edit", auth=auth)
                if post_response.status_code >= 400:
                    raise RuntimeError(f"WordPress post inspection returned HTTP {post_response.status_code}.")
                post_data = post_response.json()
                media = _inspect_reconciliation_candidate(
                    client, api, auth, settings.site_url, 31,
                    title=image.image_title or image.file_name,
                    alt_text=(assignment.override_alt_text or image.reviewed_alt_text or "").strip(),
                    checksum=local_checksum,
                )
        except (httpx.HTTPError, ValueError, RuntimeError) as exc:
            gates.append(_gate("wordpress_inspection", "Authenticated WordPress inspection succeeds", False, str(exc)))
    post_url = post_data.get("link") if isinstance(post_data.get("link"), str) else None
    gates += [
        _gate("post_identity", "Live WordPress post 8 identity matches", post_data.get("id") == 8, "Live WordPress post ID changed."),
        _gate("post_publish", "Live WordPress post 8 remains publish", post_data.get("status") == "publish", "Live WordPress post 8 is not publish."),
        _gate("post_slug", "Live Orlando slug matches", post_data.get("slug") == EXPECTED_SLUG, "Live WordPress slug changed."),
        _gate("post_url", "Live Orlando URL matches", post_url == EXPECTED_ORLANDO_URL, "Live WordPress URL changed."),
        _gate("featured_media_zero", "Post 8 currently has no featured image", post_data.get("featured_media") == 0, "Post 8 featured_media is nonzero or unverifiable."),
        _gate("media_31", "Media 31 passes complete verification", bool(media and media.valid), "Media 31 is missing, changed, attached, featured elsewhere, or byte-mismatched."),
    ]
    ready = all(gate.passed for gate in gates)
    token = phrase = expires_at = None
    if ready and media:
        expires = datetime.now(UTC) + timedelta(minutes=TOKEN_TTL_MINUTES)
        token = _sign_featured_image(local_checksum, media, post_data, expires)
        phrase = FEATURED_IMAGE_PHRASE
        expires_at = expires.isoformat()
    return WordPressFeaturedImageDryRun(
        page_id=41, wordpress_post_id=8, image_id=1, assignment_id=1,
        wordpress_media_id=31, post_status=post_data.get("status"),
        post_slug=post_data.get("slug"), post_url=post_url,
        current_featured_media=post_data.get("featured_media"), media=media,
        local_checksum=local_checksum, planned_payload={"featured_media": 31},
        excluded_media_ids=[32], gate_results=gates,
        status="featured_image_ready" if ready else "blocked", ready=ready,
        confirmation_token=token, confirmation_phrase=phrase, expires_at=expires_at,
    )


def apply_wordpress_featured_image(
    session: Session, page_id: int, request: WordPressFeaturedImageApplyRequest,
) -> WordPressFeaturedImageApplyResult:
    token = _verify_featured_image(request.confirmation_token, page_id)
    if not hmac.compare_digest(request.confirmation_phrase, FEATURED_IMAGE_PHRASE):
        raise HTTPException(status_code=422, detail="The featured-image confirmation phrase is incorrect.")
    data_backup = _backup_gate(request.confirmed_data_backup_file)
    media_backup = _archive_backup_gate(request.confirmed_media_backup_file, "media")
    program_backup = _archive_backup_gate(request.confirmed_program_backup_file, "program")
    dry = dry_run_wordpress_featured_image(session, page_id)
    gates = [*dry.gate_results, data_backup, media_backup, program_backup]
    current_snapshot = _featured_image_snapshot(dry)
    if not dry.ready or not all(g.passed for g in (data_backup, media_backup, program_backup)) or token.get("snapshot") != current_snapshot:
        raise HTTPException(status_code=409, detail="Featured-image state changed or a required gate is blocked. Run a new dry run.")
    settings = read_wordpress_settings(session)
    evidence = {
        "code": "featured_image_evidence", "passed": True,
        "request_payload": {"featured_media": 31}, "excluded_media_ids": [32],
        "backups": {
            "data": request.confirmed_data_backup_file,
            "media": request.confirmed_media_backup_file,
            "program": request.confirmed_program_backup_file,
        },
        "pre_observation": current_snapshot,
    }
    audit = WordPressMediaSyncAudit(
        generated_page_id=41, image_metadata_id=1, page_image_assignment_id=1,
        wordpress_post_id=8, wordpress_media_id=31,
        action_type="set_featured_image", status="pending",
        wordpress_site_url=settings.site_url,
        source_file_name=Path(dry.media.source_url or "media-31.png").name if dry.media else "media-31.png",
        source_mime_type="image/png", source_file_size=2_823_150,
        source_width=1672, source_height=941, source_checksum=dry.local_checksum,
        alt_text=dry.media.alt_text if dry.media and dry.media.alt_text else "",
        returned_media_url=dry.media.source_url if dry.media else None,
        gate_results=[g.model_dump(mode="json") for g in gates] + [evidence],
        backup_file_name=request.confirmed_data_backup_file,
    )
    session.add(audit); session.commit(); session.refresh(audit)
    auth = httpx.BasicAuth(settings.username, get_wordpress_application_password() or "")
    api = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2"
    wordpress_updated = False
    try:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.post(f"{api}/pages/8", json={"featured_media": 31}, auth=auth)
            if response.status_code not in {200, 201}:
                raise RuntimeError(f"WordPress featured-image update returned HTTP {response.status_code}.")
            wordpress_updated = True
            update_data = response.json()
            _verify_featured_post(update_data, "WordPress update response")
            post_response = client.get(f"{api}/pages/8?context=edit", auth=auth)
            if post_response.status_code >= 400:
                raise RuntimeError(f"WordPress post verification GET returned HTTP {post_response.status_code}.")
            verified_post = post_response.json()
            _verify_featured_post(verified_post, "WordPress verification GET")
            media_response = client.get(f"{api}/media/31?context=edit", auth=auth)
            if media_response.status_code >= 400 or media_response.json().get("id") != 31:
                raise RuntimeError("WordPress media 31 verification failed after featured-image update.")
        audit.status = "featured_image_set"; audit.completed_at = datetime.now(UTC)
        audit.gate_results = [*audit.gate_results, {
            "code": "post_apply_observation", "passed": True,
            "update_response": _post_observation(update_data),
            "verification_get": _post_observation(verified_post),
        }]
        session.add(audit); session.commit()
    except Exception as exc:
        session.rollback()
        persisted = session.get(WordPressMediaSyncAudit, audit.id)
        if persisted:
            persisted.status = "reconciliation_required" if wordpress_updated else "failed"
            persisted.completed_at = datetime.now(UTC); persisted.error_message = str(exc)
            session.add(persisted); session.commit()
        status = 500 if wordpress_updated else 502
        raise HTTPException(status_code=status, detail="Featured-image update requires inspection." if wordpress_updated else "Featured-image update failed before confirmation.") from exc
    return WordPressFeaturedImageApplyResult(
        page_id=41, wordpress_post_id=8, wordpress_media_id=31,
        status="featured_image_set", wordpress_status="publish",
        wordpress_url=EXPECTED_ORLANDO_URL, featured_media=31,
        audit_id=audit.id or 0, gate_results=gates,
    )


def _verify_featured_post(data: dict, source: str) -> None:
    mismatches = []
    for key, expected in (("id", 8), ("status", "publish"), ("featured_media", 31), ("slug", EXPECTED_SLUG), ("link", EXPECTED_ORLANDO_URL)):
        if data.get(key) != expected:
            mismatches.append(f"{key} expected {expected!r}, got {data.get(key)!r}")
    if mismatches:
        raise RuntimeError(f"{source} verification failed: " + "; ".join(mismatches))


def _post_observation(data: dict) -> dict:
    return {key: data.get(key) for key in ("id", "status", "featured_media", "slug", "link")}


def _featured_image_snapshot(dry: WordPressFeaturedImageDryRun) -> dict:
    return {
        "page_id": 41, "wordpress_post_id": 8, "image_id": 1,
        "assignment_id": 1, "wordpress_media_id": 31,
        "checksum": dry.local_checksum,
        "remote_checksum": dry.media.remote_checksum if dry.media else None,
        "media_url": dry.media.source_url if dry.media else None,
        "post": {"status": dry.post_status, "slug": dry.post_slug, "url": dry.post_url, "featured_media": dry.current_featured_media},
        "planned_payload": {"featured_media": 31}, "excluded_media_ids": [32],
    }


def _sign_featured_image(checksum: str, media: WordPressMediaReconciliationCandidate, post: dict, expires: datetime) -> str:
    dry_shape = WordPressFeaturedImageDryRun(
        page_id=41, wordpress_post_id=8, image_id=1, assignment_id=1,
        wordpress_media_id=31, post_status=post.get("status"), post_slug=post.get("slug"),
        post_url=post.get("link"), current_featured_media=post.get("featured_media"),
        media=media, local_checksum=checksum, planned_payload={"featured_media": 31},
        excluded_media_ids=[32], gate_results=[], status="featured_image_ready", ready=True,
    )
    body = {
        "action": "set_featured_image", "page_id": 41, "wordpress_post_id": 8,
        "image_id": 1, "assignment_id": 1, "wordpress_media_id": 31,
        "snapshot": _featured_image_snapshot(dry_shape),
        "expires_at": int(expires.timestamp()), "nonce": secrets.token_hex(8),
    }
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return f"{encoded}.{_encode(hmac.new(_secret, encoded.encode(), hashlib.sha256).digest())}"


def _verify_featured_image(value: str, page_id: int) -> dict:
    body = _verify_signed_body(value, "The featured-image token is invalid.")
    if body.get("action") != "set_featured_image" or body.get("page_id") != page_id or body.get("wordpress_post_id") != 8 or body.get("image_id") != 1 or body.get("assignment_id") != 1 or body.get("wordpress_media_id") != 31:
        raise HTTPException(status_code=422, detail="The featured-image token does not match the Orlando target.")
    if int(body.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status_code=422, detail="The featured-image token expired.")
    return body


def _archive_backup_gate(name: str, kind: str) -> WordPressDraftGateResult:
    pattern = rf"^atlas-{kind}-backup-(\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}})\.zip$"
    match = re.fullmatch(pattern, name)
    passed = False
    if match and Path(name).name == name:
        try:
            created = datetime.strptime(match.group(1), "%Y-%m-%d-%H%M%S").replace(tzinfo=datetime.now().astimezone().tzinfo)
            passed = timedelta(0) <= datetime.now().astimezone() - created <= timedelta(hours=24)
        except ValueError:
            passed = False
    return _gate(f"confirmed_{kind}_backup", f"Confirmed {kind.title()} Backup is current", passed, f"A valid {kind.title()} Backup filename from the last 24 hours is required.")


def _inspect_reconciliation_candidate(
    client: httpx.Client, api: str, auth: httpx.BasicAuth, site_url: str,
    media_id: int, *, title: str, alt_text: str, checksum: str,
) -> WordPressMediaReconciliationCandidate:
    response = client.get(f"{api}/media/{media_id}?context=edit", auth=auth)
    if response.status_code >= 400:
        return WordPressMediaReconciliationCandidate(wordpress_media_id=media_id, valid=False, gate_results=[_gate("media_get", f"Media {media_id} GET", False, f"HTTP {response.status_code}.")])
    data = response.json()
    details = data.get("media_details") if isinstance(data.get("media_details"), dict) else {}
    source_url = data.get("source_url") if isinstance(data.get("source_url"), str) else None
    parent = data.get("post")
    record_title = _wp_text(data.get("title"))
    size = data.get("filesize") if isinstance(data.get("filesize"), int) else details.get("filesize")
    width, height = details.get("width"), details.get("height")
    source_ok = _safe_remote_url(source_url, site_url)
    remote_hash = None
    remote_size = 0
    download_error = None
    if source_ok and source_url:
        try:
            remote_hash, remote_size = _download_checksum(client, source_url, site_url)
        except (httpx.HTTPError, RuntimeError) as exc:
            download_error = str(exc)
    featured_refs: list[WordPressMediaFeaturedReference] = []
    featured_error = None
    try:
        featured_refs = _find_featured_references(client, api, auth, media_id)
    except (httpx.HTTPError, ValueError) as exc:
        featured_error = str(exc)
    gates = [
        _gate("media_id", f"Media {media_id} identity", data.get("id") == media_id, "Media ID mismatch."),
        _gate("title", f"Media {media_id} title", record_title == title, "Title mismatch."),
        _gate("alt_text", f"Media {media_id} alt text", data.get("alt_text") == alt_text, "Alt text mismatch."),
        _gate("mime", f"Media {media_id} MIME", data.get("mime_type") == "image/png", "MIME mismatch."),
        _gate("dimensions", f"Media {media_id} dimensions", width == 1672 and height == 941, "Dimensions mismatch."),
        _gate("size", f"Media {media_id} file size", size == 2_823_150 and remote_size == 2_823_150, "File size mismatch."),
        _gate("source_url", f"Media {media_id} source URL", source_ok, "Source URL is missing, non-HTTPS, or outside the WordPress host."),
        _gate("parent", f"Media {media_id} is unattached", parent in {None, 0}, "Attachment has a parent post."),
        _gate(
            "not_featured_elsewhere", f"Media {media_id} is not featured elsewhere",
            featured_error is None and not featured_refs,
            featured_error or _featured_reference_message(featured_refs),
        ),
        _gate("remote_download", f"Media {media_id} original downloads safely", download_error is None and remote_hash is not None, download_error or "Remote download failed."),
        _gate("remote_checksum", f"Media {media_id} byte hash matches Atlas", remote_hash == checksum, "Remote SHA-256 does not match Atlas."),
    ]
    return WordPressMediaReconciliationCandidate(
        wordpress_media_id=media_id, date_gmt=data.get("date_gmt"), source_url=source_url,
        title=record_title, alt_text=data.get("alt_text"), mime_type=data.get("mime_type"),
        width=width, height=height, file_size=size, parent_post_id=parent,
        remote_checksum=remote_hash, featured_references=featured_refs,
        valid=all(g.passed for g in gates), gate_results=gates,
    )


def _find_featured_references(
    client: httpx.Client, api: str, auth: httpx.BasicAuth, media_id: int,
) -> list[WordPressMediaFeaturedReference]:
    references: list[WordPressMediaFeaturedReference] = []
    for object_type, collection in (("page", "pages"), ("post", "posts")):
        response = client.get(f"{api}/{collection}?context=edit&per_page=100", auth=auth)
        if response.status_code >= 400:
            raise ValueError(f"WordPress {collection} featured-media inspection returned HTTP {response.status_code}.")
        records = response.json()
        if not isinstance(records, list):
            raise ValueError(f"WordPress {collection} featured-media inspection returned invalid JSON.")
        for record in records:
            if not isinstance(record, dict) or record.get("featured_media") != media_id or not isinstance(record.get("id"), int):
                continue
            references.append(WordPressMediaFeaturedReference(
                object_type=object_type, object_id=record["id"], title=_wp_text(record.get("title")),
                status=record.get("status"), slug=record.get("slug"), link=record.get("link"),
            ))
    return references


def _featured_reference_message(references: list[WordPressMediaFeaturedReference]) -> str:
    if not references:
        return "Attachment featured-media usage could not be verified."
    details = ", ".join(
        f"{reference.object_type} {reference.object_id} ({reference.title or reference.slug or 'untitled'}, status {reference.status or 'unknown'})"
        for reference in references
    )
    return f"Attachment is featured by: {details}."


def _candidate_selection_failure(candidates: list[WordPressMediaReconciliationCandidate]) -> str:
    hash_matches = [
        candidate for candidate in candidates
        if any(gate.code == "remote_checksum" and gate.passed for gate in candidate.gate_results)
    ]
    featured_blocked = [
        candidate for candidate in hash_matches
        if any(gate.code == "not_featured_elsewhere" and not gate.passed for gate in candidate.gate_results)
    ]
    if hash_matches and len(featured_blocked) == len(hash_matches):
        details = "; ".join(
            f"media {candidate.wordpress_media_id}: {_featured_reference_message(candidate.featured_references)}"
            for candidate in featured_blocked
        )
        return f"No byte-matching candidate qualified because of featured-media usage. {details}"
    failed = sorted({
        gate.code for candidate in candidates for gate in candidate.gate_results if not gate.passed
    })
    return "No candidate qualified; failed gates: " + (", ".join(failed) if failed else "candidate inspection unavailable") + "."


def _safe_remote_url(value: str | None, site_url: str) -> bool:
    if not value:
        return False
    parsed, expected = urlparse(value), urlparse(site_url)
    return parsed.scheme == "https" and parsed.hostname == expected.hostname and parsed.port == expected.port


def _download_checksum(client: httpx.Client, source_url: str, site_url: str) -> tuple[str, int]:
    url = source_url
    maximum = get_settings().media_max_upload_bytes
    for _ in range(4):
        if not _safe_remote_url(url, site_url):
            raise RuntimeError("Remote media URL or redirect is outside the configured WordPress host.")
        with client.stream("GET", url) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location:
                    raise RuntimeError("Remote media redirect omitted Location.")
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                raise RuntimeError(f"Remote media download returned HTTP {response.status_code}.")
            digest, total = hashlib.sha256(), 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > maximum:
                    raise RuntimeError("Remote media exceeds the configured maximum size.")
                digest.update(chunk)
            return digest.hexdigest(), total
    raise RuntimeError("Remote media exceeded the redirect limit.")


def _select_reconciliation_candidate(
    candidates: list[WordPressMediaReconciliationCandidate],
) -> tuple[WordPressMediaReconciliationCandidate | None, list[int]]:
    valid = [candidate for candidate in candidates if candidate.valid]
    if not valid:
        return None, []
    valid.sort(key=lambda candidate: (candidate.date_gmt or "9999", candidate.wordpress_media_id))
    return valid[0], [candidate.wordpress_media_id for candidate in valid[1:]]


def _sign_reconciliation(
    checksum: str, candidates: list[WordPressMediaReconciliationCandidate],
    selected_media_id: int, duplicate_ids: list[int], expires: datetime,
) -> str:
    body = {
        "action": "reconcile_existing_media", "page_id": 41, "wordpress_post_id": 8,
        "image_id": 1, "assignment_id": 1, "checksum": checksum,
        "candidate_ids": list(CANDIDATE_MEDIA_IDS), "selected_media_id": selected_media_id,
        "duplicate_candidate_ids": duplicate_ids,
        "remote_hashes": {str(c.wordpress_media_id): c.remote_checksum for c in candidates},
        "expires_at": int(expires.timestamp()), "nonce": secrets.token_hex(8),
    }
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return f"{encoded}.{_encode(hmac.new(_secret, encoded.encode(), hashlib.sha256).digest())}"


def _verify_reconciliation(value: str, page_id: int) -> dict:
    body = _verify_signed_body(value, "The reconciliation token is invalid.")
    if body.get("action") != "reconcile_existing_media" or body.get("page_id") != page_id or body.get("wordpress_post_id") != 8 or body.get("image_id") != 1 or body.get("assignment_id") != 1:
        raise HTTPException(status_code=422, detail="The reconciliation token does not match the Orlando target.")
    if int(body.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()):
        raise HTTPException(status_code=422, detail="The reconciliation token expired.")
    return body


def _verify_signed_body(value: str, error: str) -> dict:
    try:
        encoded, supplied = value.split(".", 1)
        expected = _encode(hmac.new(_secret, encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected): raise ValueError
        return json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail=error)


def _resolve_media_path(image: ImageMetadata) -> tuple[Path | None, str | None]:
    asset_url = (image.asset_url or "").replace("\\", "/")
    if asset_url:
        parts = asset_url.split("/")
        if (
            not asset_url.startswith("/media/")
            or len(parts) != 3
            or not parts[2]
            or parts[2] in {".", ".."}
            or ":" in parts[2]
        ):
            return None, "The Atlas asset URL must be a single file inside /media/."
        name = parts[2]
    else:
        source = (image.stored_filename or image.file_name or "").replace("\\", "/")
        if not source or "/" in source or ":" in source or source in {".", ".."}:
            return None, "Path traversal and paths outside approved media roots are blocked."
        name = source
    roots = [Path("/frontend/public/media"), Path("/atlas-program/frontend/public/media"), Path(__file__).resolve().parents[3] / "frontend" / "public" / "media"]
    for root in roots:
        candidate = root / name
        if candidate.is_file():
            resolved_root, resolved = root.resolve(), candidate.resolve()
            if candidate.is_symlink() or not resolved.is_relative_to(resolved_root): return None, "Symlinks and paths outside approved media roots are blocked."
            return resolved, None
    return None, "Assigned hero image does not exist in an approved media root."


def _not_already_mapped_gate(
    image: ImageMetadata,
    match: WordPressMediaAttachmentMatch,
) -> WordPressDraftGateResult:
    verified_match = match.status == "matched" and match.wordpress_media_id is not None
    return _gate(
        "not_already_mapped",
        "Image is not already uploaded",
        not verified_match,
        "A verified WordPress attachment already exists; reconcile instead of uploading.",
    )


def _inspect_file(path: Path) -> tuple[str, int, int, int, str, str | None]:
    try:
        data = path.read_bytes(); mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with Image.open(path) as img:
            img.verify(); fmt = img.format
        with Image.open(path) as img: width, height = img.size
        if mime not in ALLOWED_MIME or ALLOWED_MIME[mime] != fmt: return mime, len(data), width, height, "", "Extension, MIME type, or decoded format is unsupported or mismatched."
        cfg = get_settings()
        if len(data) > cfg.media_max_upload_bytes: return mime, len(data), width, height, "", "Image exceeds the configured upload size limit."
        if width <= 0 or height <= 0 or width * height > cfg.media_max_pixels: return mime, len(data), width, height, "", "Image dimensions are invalid or exceed the pixel limit."
        return mime, len(data), width, height, hashlib.sha256(data).hexdigest(), None
    except (OSError, UnidentifiedImageError): return "application/octet-stream", 0, 0, 0, "", "Image file is corrupt or unreadable."


def _attachment_match(site: str, username: str, password: str, image: ImageMetadata, checksum: str) -> WordPressMediaAttachmentMatch:
    endpoint = f"{site.rstrip('/')}/wp-json/wp/v2/media"
    auth = httpx.BasicAuth(username, password)
    try:
        with httpx.Client(timeout=12.0, follow_redirects=True) as client:
            if image.wordpress_media_id:
                r = client.get(f"{endpoint}/{image.wordpress_media_id}?context=edit", auth=auth)
                if r.status_code >= 400: return WordPressMediaAttachmentMatch(status="blocked", message="Saved WordPress media mapping could not be verified.")
                items = [r.json()]
            else:
                r = client.get(f"{endpoint}?context=edit&per_page=20&search={quote(Path(image.file_name).stem)}", auth=auth)
                if r.status_code >= 400: return WordPressMediaAttachmentMatch(status="unavailable", message=f"WordPress media search returned HTTP {r.status_code}.")
                items = r.json()
        matches = []
        for item in items if isinstance(items, list) else []:
            meta = item.get("meta") or {}
            if str(meta.get("_atlas_managed_media", "")).lower() == "true" and str(meta.get("_atlas_image_metadata_id")) == "1" and str(meta.get("_atlas_generated_page_id")) == "41":
                if meta.get("_atlas_source_checksum") != checksum: return WordPressMediaAttachmentMatch(status="blocked", message="An Atlas-managed attachment exists with a different checksum.")
                matches.append(item)
        if len(matches) > 1: return WordPressMediaAttachmentMatch(status="blocked", message="Multiple Atlas-managed checksum matches require manual review.")
        if len(matches) == 1: return WordPressMediaAttachmentMatch(status="matched", wordpress_media_id=matches[0].get("id"), wordpress_media_url=matches[0].get("source_url"), message="A verified Atlas-managed attachment already exists.")
        return WordPressMediaAttachmentMatch(status="missing", message="No Atlas-managed attachment with this checksum exists.")
    except (httpx.HTTPError, ValueError): return WordPressMediaAttachmentMatch(status="unavailable", message="WordPress media search failed or returned invalid data.")


def _backup_gate(name: str) -> WordPressDraftGateResult:
    try:
        if Path(name).name != name: raise BackupValidationError("Invalid backup filename.")
        payload = load_backup(resolve_backup_download(name))
        created = datetime.fromisoformat(payload["metadata"]["created_at"])
        if created.tzinfo is None: created = created.replace(tzinfo=UTC)
        return _gate("confirmed_backup", "Confirmed Data Backup JSON is current", datetime.now(UTC) - created <= timedelta(hours=24), "A valid Data Backup JSON from the last 24 hours is required.")
    except (BackupValidationError, OSError, ValueError): return _gate("confirmed_backup", "Confirmed Data Backup JSON is current", False, "The confirmed Data Backup JSON is missing, invalid, or stale.")


def _sign(page_id: int, checksum: str, expires: datetime) -> str:
    body = {"action":"upload_media","page_id":page_id,"wordpress_post_id":8,"assignment_id":1,"image_id":1,"checksum":checksum,"expires_at":int(expires.timestamp()),"nonce":secrets.token_hex(8)}
    encoded = _encode(json.dumps(body, sort_keys=True, separators=(",", ":")).encode())
    return f"{encoded}.{_encode(hmac.new(_secret, encoded.encode(), hashlib.sha256).digest())}"


def _verify(value: str, page_id: int) -> dict:
    try:
        encoded, supplied = value.split(".", 1); expected = _encode(hmac.new(_secret, encoded.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied, expected): raise ValueError
        body = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (ValueError, TypeError, json.JSONDecodeError): raise HTTPException(status_code=422, detail="The media upload token is invalid.")
    if body.get("action") != "upload_media" or body.get("page_id") != page_id or body.get("wordpress_post_id") != 8 or body.get("assignment_id") != 1 or body.get("image_id") != 1: raise HTTPException(status_code=422, detail="The media upload token does not match the Orlando hero image.")
    if int(body.get("expires_at", 0)) < int(datetime.now(UTC).timestamp()): raise HTTPException(status_code=422, detail="The media upload token expired.")
    return body


def _encode(value: bytes) -> str: return base64.urlsafe_b64encode(value).decode().rstrip("=")
def _gate(code: str, label: str, passed: bool, failure: str) -> WordPressDraftGateResult: return WordPressDraftGateResult(code=code, label=label, passed=passed, message="Passed." if passed else failure)
