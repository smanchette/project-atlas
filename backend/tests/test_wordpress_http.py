from __future__ import annotations

from pathlib import Path
import socket
import ssl
from types import SimpleNamespace

import httpx
import pytest

from app.services import wordpress_http


@pytest.fixture(autouse=True)
def verified_release(monkeypatch: pytest.MonkeyPatch):
    wordpress_http.wordpress_user_agent.cache_clear()
    monkeypatch.setattr(wordpress_http, "resolve_program_root", lambda: Path("/atlas-program"))
    monkeypatch.setattr(
        wordpress_http,
        "verify_runtime_release_identity",
        lambda _root: SimpleNamespace(atlas_version="v0.59.89"),
    )
    yield
    wordpress_http.wordpress_user_agent.cache_clear()


def test_shared_anonymous_and_authenticated_clients_send_exact_user_agent():
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={"ok": True}, request=request)

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        timeout=8,
        follow_redirects=False,
        transport=httpx.MockTransport(handler),
    ) as client:
        client.get("https://wordpress.example/wp-json/")
        client.get(
            "https://wordpress.example/wp-json/wp/v2/users/me?context=edit",
            auth=wordpress_http.wordpress_basic_auth("atlas", "local-only"),
        )

    assert wordpress_http.wordpress_user_agent() == "Project-Atlas-WordPress/v0.59.89"
    assert [request.headers["user-agent"] for request in captured] == [
        "Project-Atlas-WordPress/v0.59.89",
        "Project-Atlas-WordPress/v0.59.89",
    ]
    assert all(request.headers["accept"] == "application/json" for request in captured)
    assert "authorization" not in captured[0].headers
    assert len(captured[1].headers.get_list("authorization")) == 1
    assert captured[1].headers["authorization"].startswith("Basic ")
    assert all(not request.headers["user-agent"].startswith("python-httpx/") for request in captured)


def test_user_agent_cannot_be_overridden_by_factory_or_request():
    with pytest.raises(ValueError, match="cannot be overridden"):
        wordpress_http.wordpress_http_client(
            "https://wordpress.example",
            timeout=8,
            follow_redirects=False,
            headers={"User-Agent": "arbitrary"},
        )

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        timeout=8,
        follow_redirects=False,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, request=request)),
    ) as client:
        with pytest.raises(httpx.RequestError, match="User-Agent policy"):
            client.get("https://wordpress.example/wp-json/", headers={"User-Agent": "arbitrary"})


def test_shared_defaults_keep_tls_verification_enabled():
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    client = wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        client_factory=FakeClient,
    )
    assert isinstance(client, FakeClient)
    assert captured["timeout"] == wordpress_http.DEFAULT_WORDPRESS_TIMEOUT
    assert captured["follow_redirects"] is False
    assert captured["verify"] is True

    with pytest.raises(ValueError, match="TLS verification cannot be disabled"):
        wordpress_http.wordpress_http_client(
            "https://wordpress.example",
            verify=False,
        )


def test_arbitrary_host_and_authenticated_cross_host_redirect_fail_closed():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "https://other.example/wp-json/"}, request=request)

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        timeout=8,
        follow_redirects=True,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.RequestError, match="left the configured origin"):
            client.get(
                "https://wordpress.example/wp-json/",
                auth=wordpress_http.wordpress_basic_auth("atlas", "local-only"),
            )
        with pytest.raises(httpx.RequestError, match="left the configured origin"):
            client.get("https://other.example/wp-json/")


@pytest.mark.parametrize(
    "location",
    [
        "http://wordpress.example/wp-json/",
        "https://www.wordpress.example/wp-json/",
        "https://other.example/wp-json/",
    ],
)
def test_authenticated_redirect_origin_variants_fail_closed(location: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": location}, request=request)

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        follow_redirects=True,
        transport=httpx.MockTransport(handler),
    ) as client:
        with pytest.raises(httpx.RequestError, match="left the configured origin"):
            client.get(
                "https://wordpress.example/wp-json/",
                auth=wordpress_http.wordpress_basic_auth("atlas", "local-only"),
            )


def test_authenticated_same_origin_redirect_is_allowed_and_auth_is_single():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/wp-json/":
            return httpx.Response(302, headers={"Location": "/wp-json/wp/v2/users/me"}, request=request)
        return httpx.Response(200, json={"id": 7}, request=request)

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        follow_redirects=True,
        transport=httpx.MockTransport(handler),
    ) as client:
        response = client.get(
            "https://wordpress.example/wp-json/",
            auth=wordpress_http.wordpress_basic_auth("atlas", "local-only"),
        )

    assert response.status_code == 200
    assert len(requests) == 2
    assert all(len(request.headers.get_list("authorization")) == 1 for request in requests)


def test_caller_authorization_headers_and_duplicates_fail_closed():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, request=request))
    with pytest.raises(ValueError, match="Authorization"):
        wordpress_http.wordpress_http_client(
            "https://wordpress.example",
            headers={"Authorization": "Bearer arbitrary"},
        )

    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        transport=transport,
    ) as client:
        with pytest.raises(httpx.RequestError, match="Authorization"):
            client.get(
                "https://wordpress.example/wp-json/",
                headers={"Authorization": "Bearer arbitrary"},
            )
        with pytest.raises(httpx.RequestError, match="Caller-supplied Authorization"):
            client.get(
                "https://wordpress.example/wp-json/",
                headers={"Authorization": "Basic arbitrary"},
                auth=wordpress_http.wordpress_basic_auth("atlas", "local-only"),
            )
        with pytest.raises(httpx.RequestError, match="Duplicate Authorization"):
            client.get(
                "https://wordpress.example/wp-json/",
                headers=httpx.Headers(
                    [("Authorization", "Basic first"), ("Authorization", "Basic second")]
                ),
            )


@pytest.mark.parametrize("timeout", [0.5, 60.1, float("inf")])
def test_timeout_outside_policy_bounds_fails_closed(timeout: float):
    with pytest.raises(ValueError, match="between 1 and 60 seconds"):
        wordpress_http.wordpress_http_client(
            "https://wordpress.example",
            timeout=timeout,
        )


def test_response_source_classification_distinguishes_security_and_wordpress():
    security = httpx.Response(403, headers={"Content-Type": "text/html"}, text="blocked")
    anonymous = httpx.Response(
        401,
        headers={"Content-Type": "application/json"},
        json={"code": "rest_not_logged_in"},
    )
    permission = httpx.Response(
        403,
        headers={"Content-Type": "application/json"},
        json={"code": "rest_forbidden"},
    )
    assert wordpress_http.classify_wordpress_response(security) == (
        "security_layer_block",
        "security_layer_html_403",
    )
    assert wordpress_http.classify_wordpress_response(anonymous) == (
        "wordpress_json_authentication_error",
        "wordpress_credentials_rejected",
    )
    assert wordpress_http.classify_wordpress_response(permission) == (
        "wordpress_json_authorization_error",
        "wordpress_permission_denied",
    )


def test_transport_classification_distinguishes_timeout_tls_and_network():
    request = httpx.Request("GET", "https://wordpress.example/wp-json/")
    timeout = httpx.ReadTimeout("timed out", request=request)
    tls_cause = ssl.SSLError("certificate failed")
    tls = httpx.ConnectError("TLS failed", request=request)
    tls.__cause__ = tls_cause
    network = httpx.ConnectError("DNS failed", request=request)

    assert wordpress_http.classify_wordpress_exception(timeout) == (
        "timeout",
        "wordpress_request_timeout",
    )
    assert wordpress_http.classify_wordpress_exception(tls) == (
        "tls_error",
        "wordpress_tls_error",
    )
    assert wordpress_http.classify_wordpress_exception(network) == (
        "network_error",
        "wordpress_dns_or_network_error",
    )


def test_public_transport_classification_is_precise_and_safe():
    request = httpx.Request("GET", "https://wordpress.example/")
    tls = httpx.ConnectError("sensitive TLS detail", request=request)
    tls.__cause__ = ssl.SSLError("certificate detail")
    dns = httpx.ConnectError("sensitive DNS detail", request=request)
    dns.__cause__ = socket.gaierror("resolver detail")
    cases = [
        (httpx.ConnectTimeout("secret", request=request), "connect_timeout"),
        (httpx.ReadTimeout("secret", request=request), "read_timeout"),
        (tls, "tls_failed"),
        (dns, "dns_failed"),
        (httpx.ConnectError("secret", request=request), "network_failed"),
    ]
    for exception, expected in cases:
        category, reason = wordpress_http.classify_public_transport_exception(exception)
        assert category == expected
        assert reason.startswith("public_transport_")
        assert "secret" not in reason


def test_siteground_like_fixture_blocks_default_httpx_and_allows_atlas_policy():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["user-agent"].startswith("python-httpx/"):
            return httpx.Response(403, headers={"Content-Type": "text/html"}, request=request)
        return httpx.Response(200, json={"name": "My WordPress"}, request=request)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as default_client:
        assert default_client.get("https://wordpress.example/wp-json/").status_code == 403
    with wordpress_http.wordpress_http_client(
        "https://wordpress.example",
        timeout=8,
        follow_redirects=False,
        transport=transport,
    ) as atlas_client:
        assert atlas_client.get("https://wordpress.example/wp-json/").status_code == 200


def test_active_wordpress_call_sites_use_shared_policy():
    services = Path(__file__).resolve().parents[1] / "app" / "services"
    offenders: list[str] = []
    for path in services.glob("wordpress_*.py"):
        if path.name == "wordpress_http.py":
            continue
        source = path.read_text(encoding="utf-8")
        if "with httpx.Client(" in source or "httpx.BasicAuth(" in source:
            offenders.append(path.name)
        if "client_factory=httpx.Client" in source and "wordpress_http_client" not in source:
            offenders.append(path.name)
    assert offenders == []
