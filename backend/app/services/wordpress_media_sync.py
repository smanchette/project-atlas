from datetime import UTC, datetime, timedelta
import base64
import hashlib
import hmac
import json
import mimetypes
from pathlib import Path
import secrets
from urllib.parse import quote

import httpx
from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError
from sqlmodel import Session, select

from app.core.config import get_settings
from app.db.backup import BackupValidationError, load_backup, resolve_backup_download
from app.models import GeneratedPage, ImageMetadata, PageImageAssignment, WordPressMediaSyncAudit
from app.schemas.wordpress import (
    WordPressDraftGateResult, WordPressMediaAttachmentMatch, WordPressMediaDryRun,
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
            markers = {"_atlas_source_checksum": dry.checksum, "_atlas_image_metadata_id": "1", "_atlas_generated_page_id": "41", "_atlas_managed_media": "true"}
            patched = client.post(f"{endpoint}/{media_id}", json={"alt_text": dry.alt_text, "title": dry.image_title, "meta": markers}, auth=httpx.BasicAuth(settings.username, password))
            if patched.status_code not in {200, 201}: raise RuntimeError(f"WordPress metadata update returned HTTP {patched.status_code}.")
            verified = client.get(f"{endpoint}/{media_id}?context=edit", auth=httpx.BasicAuth(settings.username, password))
            verify_data = verified.json() if verified.status_code < 400 else {}
            media_url = verify_data.get("source_url")
            meta = verify_data.get("meta") or {}
            if verify_data.get("id") != media_id or verify_data.get("alt_text") != dry.alt_text or verify_data.get("mime_type") != dry.mime_type or not isinstance(media_url, str) or meta.get("_atlas_source_checksum") != dry.checksum:
                raise RuntimeError("WordPress attachment verification failed.")
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
