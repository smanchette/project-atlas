from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import City, County, GeneratedPage, Service, WordPressDraftAudit
from app.schemas.wordpress import (
    WordPressDraftComparison,
    WordPressDraftRequestPayload,
    WordPressDraftReviewDetail,
    WordPressDraftReviewItem,
    WordPressDraftReviewList,
    WordPressLiveDraftStatus,
)
from app.services.wordpress_drafts import _payload_hash
from app.services.wordpress_sandbox import (
    build_wordpress_payload_preview,
    get_wordpress_application_password,
    read_wordpress_settings,
)
from app.services.wordpress_http import wordpress_basic_auth, wordpress_http_client


def list_wordpress_draft_reviews(session: Session) -> WordPressDraftReviewList:
    pages = session.exec(
        select(GeneratedPage)
        .where(GeneratedPage.wordpress_post_id.is_not(None))
        .order_by(GeneratedPage.last_wordpress_sync_at.desc(), GeneratedPage.id)
    ).all()
    items = [_review_item(session, page) for page in pages if page.wordpress_post_id is not None]
    return WordPressDraftReviewList(total_count=len(items), items=items)


def get_wordpress_draft_review(session: Session, page_id: int) -> WordPressDraftReviewDetail:
    page = _draft_page(session, page_id)
    return WordPressDraftReviewDetail(
        item=_review_item(session, page),
        comparison=_comparison(session, page, live_status=None),
    )


def check_live_wordpress_draft_status(
    session: Session,
    page_id: int,
) -> WordPressLiveDraftStatus:
    page = _draft_page(session, page_id)
    settings = read_wordpress_settings(session)
    password = get_wordpress_application_password()
    if settings.publishing_mode != "sandbox":
        return _live_error(
            page,
            "WordPress mode must be sandbox to run a read-only status check.",
            credentials_present=bool(settings.username and password),
        )
    if not settings.site_url:
        return _live_error(
            page,
            "WordPress site URL is required.",
            credentials_present=bool(settings.username and password),
        )
    if not settings.username or not password:
        return _live_error(
            page,
            "WordPress username and process-memory application password are required for the read-only status check.",
            credentials_present=False,
        )

    endpoint = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/pages/{page.wordpress_post_id}?context=edit"
    try:
        with wordpress_http_client(settings.site_url, timeout=10.0, follow_redirects=True, client_factory=httpx.Client) as client:
            response = client.get(
                endpoint,
                auth=wordpress_basic_auth(settings.username, password),
            )
    except httpx.HTTPError as exc:
        return _live_error(
            page,
            f"WordPress status check failed: {exc.__class__.__name__}.",
            credentials_present=True,
        )

    if response.status_code == 404:
        return _live_error(page, "WordPress draft was not found.", rest_api_reachable=True, authenticated=True, credentials_present=True)
    if response.status_code in {401, 403}:
        return _live_error(page, "WordPress status check was unauthorized.", rest_api_reachable=True, authenticated=False, credentials_present=True)
    if response.status_code >= 400:
        return _live_error(page, f"WordPress returned HTTP {response.status_code}.", rest_api_reachable=True, authenticated=True, credentials_present=True)

    try:
        payload = response.json()
    except ValueError:
        return _live_error(page, "WordPress returned a non-JSON response.", rest_api_reachable=True, authenticated=True, credentials_present=True)

    status = _string(payload.get("status"))
    link = _string(payload.get("link"))
    title = payload.get("title") if isinstance(payload.get("title"), dict) else {}
    return WordPressLiveDraftStatus(
        page_id=page.id or page_id,
        wordpress_post_id=page.wordpress_post_id or 0,
        rest_api_reachable=True,
        authenticated=True,
        credentials_present=True,
        wordpress_status=status,
        wordpress_link=link,
        wordpress_modified=_string(payload.get("modified_gmt") or payload.get("modified")),
        wordpress_title=_string(title.get("rendered")) if isinstance(title, dict) else None,
        wordpress_slug=_string(payload.get("slug")),
        is_still_draft=status == "draft",
        appears_published=status == "publish",
    )


def compare_wordpress_draft(
    session: Session,
    page_id: int,
    *,
    live_status: WordPressLiveDraftStatus | None = None,
) -> WordPressDraftComparison:
    return _comparison(session, _draft_page(session, page_id), live_status=live_status)


def _draft_page(session: Session, page_id: int) -> GeneratedPage:
    page = session.get(GeneratedPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="Generated page not found")
    if page.wordpress_post_id is None:
        raise HTTPException(status_code=404, detail="Generated page does not have a WordPress draft reference")
    return page


def _review_item(session: Session, page: GeneratedPage) -> WordPressDraftReviewItem:
    city = session.get(City, page.city_id) if page.city_id else None
    county = session.get(County, page.county_id) if page.county_id else None
    service = session.get(Service, page.service_id)
    successful_audits = _successful_audits(session, page.id or 0)
    latest = successful_audits[0] if successful_audits else None
    return WordPressDraftReviewItem(
        page_id=page.id or 0,
        page_title=page.page_title,
        city=city.city_name if city else None,
        county=county.county_name if county else None,
        service=service.service_name if service else None,
        atlas_status=page.status,
        qa_status=page.qa_status,
        wordpress_post_id=page.wordpress_post_id or 0,
        wordpress_status=page.wordpress_status,
        wordpress_url=page.wordpress_url,
        last_wordpress_sync_at=page.last_wordpress_sync_at.isoformat() if page.last_wordpress_sync_at else None,
        successful_draft_audit_count=len(successful_audits),
        latest_draft_audit_at=latest.attempted_at.isoformat() if latest else None,
        audit_payload_hash=latest.payload_hash if latest else None,
        audit_draft_hash=latest.draft_hash_at_attempt if latest else None,
        admin_edit_url=_admin_edit_url(page, latest),
        badges=_badges(page, latest, current_payload_hash=_current_payload_hash(session, page.id or 0)),
    )


def _comparison(
    session: Session,
    page: GeneratedPage,
    *,
    live_status: WordPressLiveDraftStatus | None,
) -> WordPressDraftComparison:
    audits = _successful_audits(session, page.id or 0)
    latest = audits[0] if audits else None
    current_hash = _current_payload_hash(session, page.id or 0)
    changed = bool(latest and latest.payload_hash != current_hash)
    return WordPressDraftComparison(
        page_id=page.id or 0,
        atlas_saved_title=page.page_title,
        wordpress_title=live_status.wordpress_title if live_status else None,
        atlas_saved_slug=page.page_slug,
        wordpress_slug=live_status.wordpress_slug if live_status else None,
        wordpress_actual_status=live_status.wordpress_status if live_status else page.wordpress_status,
        atlas_wordpress_url=page.wordpress_url,
        wordpress_link=live_status.wordpress_link if live_status else None,
        audit_payload_hash=latest.payload_hash if latest else None,
        current_export_payload_hash=current_hash,
        audit_draft_hash=latest.draft_hash_at_attempt if latest else None,
        atlas_export_differs_from_original=changed,
        message=(
            "Atlas content has changed since this WordPress draft was created. Review before updating later."
            if changed
            else "Atlas export payload matches the WordPress draft audit payload hash."
            if latest
            else "No successful draft audit is available for comparison."
        ),
    )


def _successful_audits(session: Session, page_id: int) -> list[WordPressDraftAudit]:
    return session.exec(
        select(WordPressDraftAudit)
        .where(
            WordPressDraftAudit.generated_page_id == page_id,
            WordPressDraftAudit.status == "created",
        )
        .order_by(WordPressDraftAudit.attempted_at.desc(), WordPressDraftAudit.id.desc())
    ).all()


def _current_payload_hash(session: Session, page_id: int) -> str:
    preview = build_wordpress_payload_preview(session, page_id)
    payload = WordPressDraftRequestPayload(
        title=preview.payload.title,
        slug=preview.payload.slug,
        status="draft",
        content=preview.payload.content,
        excerpt=preview.payload.excerpt,
    )
    return _payload_hash(payload)


def _admin_edit_url(page: GeneratedPage, audit: WordPressDraftAudit | None) -> str | None:
    if not page.wordpress_post_id:
        return None
    base = audit.wordpress_site_url if audit else _origin(page.wordpress_url)
    if not base:
        return None
    return f"{base.rstrip('/')}/wp-admin/post.php?post={page.wordpress_post_id}&action=edit"


def _origin(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _badges(page: GeneratedPage, audit: WordPressDraftAudit | None, *, current_payload_hash: str) -> list[str]:
    badges: list[str] = []
    if page.wordpress_status == "draft":
        badges.extend(["Draft Confirmed", "Safe Draft"])
    elif page.wordpress_status == "publish":
        badges.append("Published Warning")
    else:
        badges.append("Needs Review")
    if audit and audit.payload_hash != current_payload_hash:
        badges.append("Atlas Changed Since Draft")
    if not audit:
        badges.append("Needs Review")
    return list(dict.fromkeys(badges))


def _live_error(
    page: GeneratedPage,
    message: str,
    *,
    rest_api_reachable: bool | None = None,
    authenticated: bool | None = None,
    credentials_present: bool = False,
) -> WordPressLiveDraftStatus:
    return WordPressLiveDraftStatus(
        page_id=page.id or 0,
        wordpress_post_id=page.wordpress_post_id or 0,
        rest_api_reachable=rest_api_reachable,
        authenticated=authenticated,
        credentials_present=credentials_present,
        error_message=message,
    )


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
