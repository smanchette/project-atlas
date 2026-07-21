from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import lru_cache
import math
import re
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
