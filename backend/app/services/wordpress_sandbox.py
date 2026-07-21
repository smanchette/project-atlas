from html import escape
import os
from threading import Lock
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException
from sqlmodel import Session, select

from app.models import Setting
from app.schemas.wordpress import (
    PublishingMode,
    WordPressConnectionResult,
    WordPressHeadingContract,
    WordPressPayload,
    WordPressPayloadPreview,
    WordPressSettingsRead,
    WordPressSettingsUpdate,
)
from app.services.page_export import build_page_export_package
from app.services.wordpress_http import (
    classify_wordpress_exception,
    classify_wordpress_response,
    wordpress_basic_auth,
    wordpress_http_client,
)

SITE_URL_KEY = "wordpress_site_url"
USERNAME_KEY = "wordpress_username"
MODE_KEY = "wordpress_publishing_mode"
VALID_MODES = {"disabled", "sandbox", "draft_only_future"}

DEFAULT_WORDPRESS_HEADING_CONTRACT = WordPressHeadingContract(
    policy_id="body_owns_primary_h1",
    template_renders_primary_h1=False,
    body_heading_level=1,
)
WORDPRESS_PAGE_HEADING_CONTRACTS = {
    41: WordPressHeadingContract(
        policy_id="template_post_title_owns_primary_h1",
        template_renders_primary_h1=True,
        body_heading_level=2,
    ),
}

_secret_lock = Lock()
_application_password: str | None = None


def read_wordpress_settings(session: Session) -> WordPressSettingsRead:
    values = {
        setting.setting_key: setting.setting_value or ""
        for setting in session.exec(
            select(Setting).where(
                Setting.setting_key.in_([SITE_URL_KEY, USERNAME_KEY, MODE_KEY])
            )
        ).all()
    }
    mode = values.get(MODE_KEY, "disabled")
    if mode not in VALID_MODES:
        mode = "disabled"
    return WordPressSettingsRead(
        site_url=values.get(SITE_URL_KEY, ""),
        username=values.get(USERNAME_KEY, ""),
        publishing_mode=mode,
        has_application_password=bool(_get_application_password()),
    )


def save_wordpress_settings(
    session: Session,
    payload: WordPressSettingsUpdate,
) -> WordPressSettingsRead:
    site_url = _normalize_site_url(payload.site_url)
    values = {
        SITE_URL_KEY: (site_url, "WordPress site URL for the read-only connection sandbox."),
        USERNAME_KEY: (payload.username, "WordPress username for the local connection sandbox."),
        MODE_KEY: (payload.publishing_mode, "WordPress sandbox mode. Publishing is not implemented."),
    }
    for key, (value, description) in values.items():
        setting = session.exec(select(Setting).where(Setting.setting_key == key)).first()
        if setting is None:
            setting = Setting(setting_key=key)
        setting.setting_value = value
        setting.description = description
        session.add(setting)
    session.commit()

    if payload.clear_application_password:
        _set_application_password(None)
    elif payload.application_password:
        _set_application_password(payload.application_password)
    return read_wordpress_settings(session)


def test_wordpress_connection(session: Session) -> WordPressConnectionResult:
    settings = read_wordpress_settings(session)
    if settings.publishing_mode == "disabled":
        return WordPressConnectionResult(
            connection_status="disabled",
            rest_api_reachable=False,
            authenticated=False,
            credentials_present=bool(settings.username and _get_application_password()),
            error_message="WordPress mode is disabled. Enable sandbox mode to run a read-only test.",
        )
    if not settings.site_url:
        return _failed("WordPress site URL is required.")
    password = _get_application_password()
    rest_url = f"{settings.site_url.rstrip('/')}/wp-json/"
    auth = (
        wordpress_basic_auth(settings.username, password)
        if settings.username and password
        else None
    )
    try:
        with wordpress_http_client(
            settings.site_url,
            timeout=8.0,
            follow_redirects=True,
            client_factory=httpx.Client,
        ) as client:
            try:
                response = client.get(rest_url)
            except httpx.HTTPError as exc:
                response_source, reason_code = classify_wordpress_exception(exc)
                return _failed(
                    f"WordPress REST API request failed: {response_source}.",
                    endpoint=rest_url,
                    credentials_present=bool(settings.username and password),
                    response_source=response_source,
                    reason_code=reason_code,
                )
            response_source, reason_code = classify_wordpress_response(response)
            if response.status_code >= 400:
                return _failed(
                    f"WordPress REST API returned HTTP {response.status_code}.",
                    endpoint=rest_url,
                    credentials_present=bool(settings.username and password),
                    response_source=response_source,
                    reason_code=reason_code,
                )
            site_name = _site_name(response)
            authenticated = False
            authenticated_user_id = None
            authenticated_username = None
            atlas_status_checked = False
            atlas_status_reachable = False
            atlas_status_code = None
            if auth is not None:
                auth_url = f"{settings.site_url.rstrip('/')}/wp-json/wp/v2/users/me?context=edit"
                try:
                    auth_response = client.get(auth_url, auth=auth)
                except httpx.HTTPError as exc:
                    response_source, reason_code = classify_wordpress_exception(exc)
                    return WordPressConnectionResult(
                        connection_status="failed",
                        rest_api_reachable=True,
                        authenticated=False,
                        credentials_present=True,
                        site_name=site_name,
                        error_message=f"REST API reachable: yes. Authenticated identity request failed: {response_source}.",
                        endpoint=auth_url,
                        response_source=response_source,
                        reason_code=reason_code,
                    )
                response_source, reason_code = classify_wordpress_response(auth_response)
                identity = _json_object(auth_response)
                authenticated_user_id = identity.get("id") if isinstance(identity.get("id"), int) else None
                authenticated_username = _safe_identity_name(identity)
                authenticated = (
                    auth_response.status_code < 400
                    and response_source == "wordpress_json_success"
                    and authenticated_user_id is not None
                )
                if not authenticated:
                    return WordPressConnectionResult(
                        connection_status="failed",
                        rest_api_reachable=True,
                        authenticated=False,
                        credentials_present=True,
                        site_name=site_name,
                        error_message=(
                            "REST API reachable: yes. Authenticated: no. "
                            + (
                                "The request was blocked before WordPress could validate credentials "
                                if response_source in {"security_layer_block", "security_layer_error", "security_challenge"}
                                else "WordPress did not accept the authenticated identity request "
                            )
                            + f"(HTTP {auth_response.status_code})."
                        ),
                        endpoint=rest_url,
                        response_source=response_source,
                        reason_code=reason_code,
                    )
                atlas_status_checked = True
                status_url = f"{settings.site_url.rstrip('/')}/wp-json/project-atlas/v1/status"
                try:
                    status_response = client.get(status_url, auth=auth)
                except httpx.HTTPError as exc:
                    response_source, reason_code = classify_wordpress_exception(exc)
                else:
                    atlas_status_code = status_response.status_code
                    response_source, reason_code = classify_wordpress_response(status_response)
                    atlas_status_reachable = (
                        status_response.status_code < 400
                        and response_source == "wordpress_json_success"
                    )
            return WordPressConnectionResult(
                connection_status="connected",
                rest_api_reachable=True,
                authenticated=authenticated,
                credentials_present=bool(settings.username and password),
                site_name=site_name,
                endpoint=rest_url,
                response_source=response_source,
                reason_code=reason_code,
                authenticated_user_id=authenticated_user_id,
                authenticated_username=authenticated_username,
                atlas_status_checked=atlas_status_checked,
                atlas_status_reachable=atlas_status_reachable,
                atlas_status_code=atlas_status_code,
            )
    except httpx.HTTPError as exc:
        response_source, reason_code = classify_wordpress_exception(exc)
        return _failed(
            f"Connection failed: {response_source}.",
            endpoint=rest_url,
            credentials_present=bool(settings.username and password),
            response_source=response_source,
            reason_code=reason_code,
        )


def build_wordpress_payload_preview(
    session: Session,
    page_id: int,
) -> WordPressPayloadPreview:
    package = build_page_export_package(session, page_id)
    heading_contract = wordpress_heading_contract(package.page_id)
    hero = next(
        (item.model_dump(mode="json") for item in package.assigned_media if item.image_role == "hero"),
        None,
    )
    payload = WordPressPayload(
        title=package.page_title,
        slug=package.url_slug,
        status="draft",
        content=_content_html(
            package.model_dump(mode="json"),
            heading_contract=heading_contract,
        ),
        excerpt=package.seo.meta_description,
        featured_media_reference=hero,
        meta={
            "meta_title": package.seo.meta_title,
            "meta_description": package.seo.meta_description,
            "canonical_url_preview": package.canonical_url_preview,
        },
        schema_block_preview=package.json_ld,
    )
    return WordPressPayloadPreview(
        page_id=package.page_id,
        export_package=package.model_dump(mode="json"),
        payload=payload,
        heading_contract=heading_contract,
        warnings=[warning.model_dump(mode="json") for warning in package.warnings],
    )


def wordpress_heading_contract(page_id: int) -> WordPressHeadingContract:
    return WORDPRESS_PAGE_HEADING_CONTRACTS.get(
        page_id,
        DEFAULT_WORDPRESS_HEADING_CONTRACT,
    ).model_copy(deep=True)


def _content_html(
    package: dict[str, Any],
    *,
    heading_contract: WordPressHeadingContract = DEFAULT_WORDPRESS_HEADING_CONTRACT,
) -> str:
    level = heading_contract.body_heading_level
    parts = [f"<h{level}>{escape(str(package['h1']))}</h{level}>"]
    for key, value in package["content_sections"].items():
        parts.append(
            f'<section data-atlas-section="{escape(key)}">'
            f"<h2>{escape(key.replace('_', ' ').title())}</h2>"
            f"<p>{escape(str(value))}</p></section>"
        )
    faqs = package.get("faq_items") or []
    if faqs:
        parts.append("<section data-atlas-section=\"faqs\"><h2>Frequently Asked Questions</h2>")
        for item in faqs:
            parts.append(
                f"<h3>{escape(str(item['question']))}</h3>"
                f"<p>{escape(str(item['answer']))}</p>"
            )
        parts.append("</section>")
    if package.get("cta_block"):
        parts.append(
            '<section data-atlas-section="cta"><h2>Request an Estimate</h2>'
            f"<p>{escape(str(package['cta_block']))}</p></section>"
        )
    return "".join(parts)


def _normalize_site_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="WordPress site URL must be a valid HTTP or HTTPS URL.")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="WordPress site URL cannot contain credentials.")
    return value.rstrip("/")


def _site_name(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    name = payload.get("name") if isinstance(payload, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def _failed(
    message: str,
    *,
    endpoint: str | None = None,
    credentials_present: bool = False,
    response_source: str | None = None,
    reason_code: str | None = None,
) -> WordPressConnectionResult:
    return WordPressConnectionResult(
        connection_status="failed",
        rest_api_reachable=False,
        authenticated=False,
        credentials_present=credentials_present,
        error_message=message,
        endpoint=endpoint,
        response_source=response_source,
        reason_code=reason_code,
    )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _safe_identity_name(value: dict[str, Any]) -> str | None:
    for key in ("slug", "name"):
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _get_application_password() -> str | None:
    with _secret_lock:
        return _application_password or os.getenv("WORDPRESS_APPLICATION_PASSWORD")


def _set_application_password(value: str | None) -> None:
    global _application_password
    with _secret_lock:
        _application_password = value


def clear_wordpress_application_password() -> None:
    _set_application_password(None)


def get_wordpress_application_password() -> str | None:
    return _get_application_password()
