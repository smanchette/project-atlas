from __future__ import annotations

from collections.abc import Callable, Mapping
from email.utils import parsedate_to_datetime
from functools import lru_cache
import math
import re
import socket
import ssl
from typing import Any
from urllib.parse import urlparse

import httpx

from app.services.wordpress_deployment_release import (
    SOURCE_EXPECTATIONS,
    DeploymentReleaseError,
    resolve_program_root,
    verify_runtime_release_identity,
)


WORDPRESS_ACCEPT = "application/json"
DEFAULT_WORDPRESS_TIMEOUT = 15.0
MIN_WORDPRESS_TIMEOUT = 1.0
MAX_WORDPRESS_TIMEOUT = 60.0
_AUTH_EXTENSION = "atlas_wordpress_basic_auth"
_VERSION_PATTERN = re.compile(r"v\d+\.\d+(?:\.\d+)?")
_SAFE_DIAGNOSTIC_HEADERS = {
    "content-length",
    "content-type",
    "server",
    "sg-captcha",
    "via",
    "x-cache",
    "x-cache-enabled",
    "x-proxy-cache",
    "x-proxy-cache-info",
    "x-request-id",
    "x-sg-cache",
}
SITEGROUND_CACHE_BOUNDARY_HEADERS = {
    "age",
    "cache-control",
    "cf-cache-status",
    "content-security-policy",
    "etag",
    "expires",
    "last-modified",
    "permissions-policy",
    "referrer-policy",
    "server",
    "strict-transport-security",
    "via",
    "x-cache",
    "x-cache-enabled",
    "x-content-type-options",
    "x-frame-options",
    "x-proxy-cache",
    "x-proxy-cache-info",
    "x-sg-cache",
}
_SITEGROUND_PROXY_INFO_PATTERN = re.compile(
    r"(?:^|[\s,;])DT:\d+(?:$|[\s,;])|^\d+\s+NC:[0-9A-F]+\s+UP:$",
    re.I,
)
_CACHE_STATUS_VALUES = {"HIT", "MISS"}
_VOLATILE_CACHE_HEADERS = {
    "age",
    "cf-cache-status",
    "expires",
    "x-cache",
    "x-proxy-cache",
    "x-proxy-cache-info",
    "x-sg-cache",
}


@lru_cache(maxsize=1)
def wordpress_user_agent() -> str:
    """Return a deterministic non-browser Atlas identity without using httpx's default."""
    try:
        root = resolve_program_root()
        identity = verify_runtime_release_identity(root)
        version = identity.atlas_version
    except (DeploymentReleaseError, OSError):
        # Local tests and pre-publication source validation intentionally run before a
        # matching runtime manifest exists. The source compatibility identity is the
        # fail-safe release identifier; it can never fall back to python-httpx/*.
        match = _VERSION_PATTERN.search(SOURCE_EXPECTATIONS.source_compatibility_id)
        if match is None:
            raise RuntimeError("Atlas WordPress User-Agent identity is unavailable.")
        version = match.group(0)
    if _VERSION_PATTERN.fullmatch(version) is None:
        raise RuntimeError("Atlas WordPress User-Agent version is invalid.")
    return f"Project-Atlas-WordPress/{version}"


class _AtlasWordPressBasicAuth(httpx.BasicAuth):
    def auth_flow(self, request: httpx.Request):
        if request.headers.get_list("authorization"):
            raise httpx.RequestError(
                "Caller-supplied Authorization headers are forbidden.",
                request=request,
            )
        for authenticated_request in super().auth_flow(request):
            authenticated_request.extensions[_AUTH_EXTENSION] = True
            yield authenticated_request


def wordpress_basic_auth(username: str, password: str) -> httpx.BasicAuth:
    """Construct the one supported WordPress application-password auth scheme."""
    return _AtlasWordPressBasicAuth(username, password)


def wordpress_http_client(
    site_url: str,
    *,
    timeout: float | httpx.Timeout = DEFAULT_WORDPRESS_TIMEOUT,
    follow_redirects: bool = False,
    client_factory: Callable[..., httpx.Client] = httpx.Client,
    headers: Mapping[str, str] | None = None,
    **client_kwargs: Any,
) -> httpx.Client:
    """Create a host-bound WordPress client with the shared Atlas request policy.

    Callers retain their workflow-specific timeout and redirect choices. A request
    event hook rejects arbitrary hosts, cross-host redirects, and User-Agent
    overrides before bytes are sent.
    """
    origin = _approved_origin(site_url)
    _validate_timeout(timeout)
    if "verify" in client_kwargs and client_kwargs["verify"] is not True:
        raise ValueError("TLS verification cannot be disabled for WordPress requests.")
    client_kwargs["verify"] = True
    merged_headers = {"Accept": WORDPRESS_ACCEPT, "User-Agent": wordpress_user_agent()}
    for key, value in (headers or {}).items():
        if key.lower() == "user-agent":
            raise ValueError("The Atlas WordPress User-Agent cannot be overridden.")
        if key.lower() == "authorization":
            raise ValueError("Authorization must use the shared WordPress BasicAuth policy.")
        merged_headers[key] = value

    hooks = dict(client_kwargs.pop("event_hooks", {}) or {})
    existing = list(hooks.get("request", []))
    hooks["request"] = [lambda request: _enforce_request_policy(request, origin), *existing]
    return client_factory(
        timeout=timeout,
        follow_redirects=follow_redirects,
        headers=merged_headers,
        event_hooks=hooks,
        **client_kwargs,
    )


def classify_wordpress_response(response: httpx.Response) -> tuple[str, str]:
    """Return a safe response-source classification and stable reason code."""
    headers = getattr(response, "headers", {})
    content_type = headers.get("content-type", "").lower()
    if getattr(response, "is_redirect", False):
        return "redirect", "wordpress_redirect"
    if headers.get("sg-captcha") is not None or response.status_code == 202:
        return "security_challenge", "sg_captcha_or_challenge"
    payload: Any = None
    if "json" in content_type:
        try:
            payload = response.json()
        except ValueError:
            return "malformed_json", "malformed_wordpress_json"
        if response.status_code < 400:
            return "wordpress_json_success", "wordpress_json_success"
        code = payload.get("code") if isinstance(payload, dict) else None
        if response.status_code == 401 or code == "rest_not_logged_in":
            return "wordpress_json_authentication_error", "wordpress_credentials_rejected"
        if response.status_code == 403:
            return "wordpress_json_authorization_error", "wordpress_permission_denied"
        return "wordpress_json_error", "wordpress_json_error"
    if response.status_code == 403 and "html" in content_type:
        return "security_layer_block", "security_layer_html_403"
    if "html" in content_type and response.status_code >= 400:
        return "security_layer_error", "security_layer_html_error"
    if response.status_code >= 400:
        return "unexpected_error", "unexpected_http_error"
    return "unexpected_content_type", "unexpected_content_type"


def classify_wordpress_exception(exc: httpx.HTTPError) -> tuple[str, str]:
    """Classify transport failures without including request or credential data."""
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", "wordpress_request_timeout"
    if _exception_chain_contains(exc, ssl.SSLError):
        return "tls_error", "wordpress_tls_error"
    if isinstance(exc, (httpx.NetworkError, httpx.RequestError)):
        return "network_error", "wordpress_dns_or_network_error"
    return "request_error", "wordpress_request_error"


def classify_public_transport_exception(exc: httpx.HTTPError) -> tuple[str, str]:
    """Return a precise, non-secret category for public HTML acquisition failures."""

    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout", "public_transport_connect_timeout"
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout", "public_transport_read_timeout"
    if _exception_chain_contains(exc, ssl.SSLError):
        return "tls_failed", "public_transport_tls_failed"
    if _exception_chain_contains(exc, socket.gaierror):
        return "dns_failed", "public_transport_dns_failed"
    if isinstance(exc, httpx.TimeoutException):
        return "network_failed", "public_transport_timeout_failed"
    if isinstance(exc, (httpx.NetworkError, httpx.RequestError)):
        return "network_failed", "public_transport_network_failed"
    return "transport_acquisition_failed", "public_transport_acquisition_failed"


def classify_siteground_cache_headers(headers: Mapping[str, Any]) -> dict[str, Any]:
    """Classify already-sanitized provider headers with one shared fail-closed policy."""

    sanitized = {str(key).lower(): str(value) for key, value in headers.items()}
    if not sanitized:
        return {
            "verified": False,
            "reason_code": "cache_headers_missing",
            "status_reason_code": None,
            "headers": {},
        }
    enabled = sanitized.get("x-cache-enabled", "").lower()
    if enabled and enabled not in {"true", "false"}:
        return {
            "verified": False,
            "reason_code": "cache_header_value_invalid",
            "status_reason_code": None,
            "headers": sanitized,
        }
    raw_status = sanitized.get(
        "x-proxy-cache",
        sanitized.get("x-sg-cache", sanitized.get("x-cache", "")),
    )
    status = raw_status.strip().upper()
    status_codes = {
        "HIT": "cache_status_hit",
        "MISS": "cache_status_miss",
        "BYPASS": "cache_status_bypass",
        "EXPIRED": "cache_status_expired",
    }
    if status and status not in status_codes:
        return {
            "verified": False,
            "reason_code": "cache_header_value_invalid",
            "status_reason_code": None,
            "headers": sanitized,
        }
    proxy_info = sanitized.get("x-proxy-cache-info", "")
    proxy_info_valid = bool(_SITEGROUND_PROXY_INFO_PATTERN.search(proxy_info)) if proxy_info else False
    if proxy_info and not proxy_info_valid:
        return {
            "verified": False,
            "reason_code": "cache_header_value_invalid",
            "status_reason_code": None,
            "headers": sanitized,
        }
    verified = enabled == "true" or status in status_codes or proxy_info_valid
    return {
        "verified": verified,
        "reason_code": (
            "siteground_cache_provider_verified" if verified else "cache_provider_unrecognized"
        ),
        "status_reason_code": status_codes.get(status),
        "supporting_nginx": "nginx" in sanitized.get("server", "").lower(),
        "headers": sanitized,
    }


def compare_siteground_cache_boundaries(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare SiteGround cache observations without equating request volatility.

    Only normalized, flat, allowlisted headers are accepted. Provider identity,
    nginx origin support, cache enablement, durable cache/security headers, and
    recognized syntax remain exact. Only HIT/MISS, numeric age, parseable expiry,
    and recognized request-specific provider diagnostics may vary.
    """

    normalized: list[dict[str, str]] = []
    for label, value in (("before", before), ("after", after)):
        if not isinstance(value, Mapping):
            return {"compatible": False, "reason_code": f"{label}_cache_headers_malformed"}
        current: dict[str, str] = {}
        for raw_name, raw_value in value.items():
            if (
                not isinstance(raw_name, str)
                or raw_name != raw_name.lower()
                or raw_name not in SITEGROUND_CACHE_BOUNDARY_HEADERS
                or not isinstance(raw_value, str)
                or not raw_value.strip()
            ):
                return {
                    "compatible": False,
                    "reason_code": f"{label}_cache_header_unknown_or_malformed",
                }
            current[raw_name] = raw_value.strip()
        normalized.append(current)

    first, second = normalized
    first_provider = classify_siteground_cache_headers(first)
    second_provider = classify_siteground_cache_headers(second)
    if not all(
        item.get("verified") is True and item.get("supporting_nginx") is True
        for item in (first_provider, second_provider)
    ):
        return {"compatible": False, "reason_code": "provider_family_changed_or_unverified"}
    if first.get("server", "").lower() != second.get("server", "").lower():
        return {"compatible": False, "reason_code": "server_origin_changed"}
    if first.get("x-cache-enabled", "").lower() != second.get(
        "x-cache-enabled", ""
    ).lower():
        return {"compatible": False, "reason_code": "cache_enablement_changed"}

    durable = SITEGROUND_CACHE_BOUNDARY_HEADERS - _VOLATILE_CACHE_HEADERS
    for name in sorted(durable):
        if name in {"server", "x-cache-enabled"}:
            continue
        if first.get(name) != second.get(name):
            return {
                "compatible": False,
                "reason_code": f"durable_header_changed:{name}",
            }

    for current in (first, second):
        if current.get("x-proxy-cache", "").strip().upper() not in _CACHE_STATUS_VALUES:
            return {
                "compatible": False,
                "reason_code": "volatile_cache_status_unrecognized:x-proxy-cache",
            }
        for name in ("x-proxy-cache", "x-sg-cache", "x-cache", "cf-cache-status"):
            if name in current and current[name].strip().upper() not in _CACHE_STATUS_VALUES:
                return {
                    "compatible": False,
                    "reason_code": f"volatile_cache_status_unrecognized:{name}",
                }
        if "age" in current:
            try:
                if int(current["age"]) < 0:
                    raise ValueError
            except ValueError:
                return {"compatible": False, "reason_code": "cache_age_malformed"}
        if "expires" in current:
            try:
                if parsedate_to_datetime(current["expires"]).tzinfo is None:
                    raise ValueError
            except (TypeError, ValueError, OverflowError):
                return {"compatible": False, "reason_code": "cache_expiry_malformed"}

    return {
        "compatible": True,
        "reason_code": "recognized_siteground_request_cache_volatility",
        "before": first,
        "after": second,
    }


def sanitized_response_diagnostics(response: httpx.Response) -> dict[str, Any]:
    source, reason = classify_wordpress_response(response)
    return {
        "status_code": response.status_code,
        "final_url": str(response.url),
        "redirect_count": len(response.history),
        "response_source": source,
        "reason_code": reason,
        "headers": {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in _SAFE_DIAGNOSTIC_HEADERS
        },
    }


def _approved_origin(site_url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(site_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("A valid WordPress HTTP(S) origin is required.")
    if parsed.username or parsed.password:
        raise ValueError("The WordPress origin cannot contain credentials.")
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port


def _enforce_request_policy(request: httpx.Request, origin: tuple[str, str, int | None]) -> None:
    requested = (request.url.scheme.lower(), (request.url.host or "").lower(), request.url.port)
    if requested != origin:
        raise httpx.RequestError(
            "WordPress request or redirect left the configured origin.",
            request=request,
        )
    if request.headers.get("user-agent") != wordpress_user_agent():
        raise httpx.RequestError(
            "Atlas WordPress User-Agent policy was overridden.",
            request=request,
        )
    authorization = request.headers.get_list("authorization")
    if len(authorization) > 1:
        raise httpx.RequestError("Duplicate Authorization headers are forbidden.", request=request)
    if authorization and (
        request.extensions.get(_AUTH_EXTENSION) is not True
        or not authorization[0].startswith("Basic ")
    ):
        raise httpx.RequestError(
            "Authorization must use the shared WordPress BasicAuth policy.",
            request=request,
        )


def _validate_timeout(timeout: float | httpx.Timeout) -> None:
    configured = timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
    for value in configured.as_dict().values():
        if value is None:
            continue
        if not math.isfinite(value) or not MIN_WORDPRESS_TIMEOUT <= value <= MAX_WORDPRESS_TIMEOUT:
            raise ValueError(
                f"WordPress timeout values must be between {MIN_WORDPRESS_TIMEOUT:g} "
                f"and {MAX_WORDPRESS_TIMEOUT:g} seconds."
            )


def _exception_chain_contains(exc: BaseException, kind: type[BaseException]) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        if isinstance(current, kind):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False
