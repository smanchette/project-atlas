from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import runpy
import sys

import httpx
import pytest

from app.schemas.wordpress import WordPressManualBrowserEvidence
from app.services.wordpress_rendered_state import (
    CANONICAL_EVIDENCE_TIMESTAMP_PATTERN,
    CAPTURE_HELPER_VERSION,
    EVIDENCE_SCHEMA,
    EVIDENCE_SCHEMA_VERSION,
    EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1,
    EXPECTED_BODY_H1,
    EXPECTED_H1,
    EXPECTED_MEDIA_ALT,
    EXPECTED_MEDIA_URL,
    EXPECTED_TITLE,
    EXPECTED_URL,
    _canonical_json,
    _evidence_payload,
    acquire_rendered_state,
    build_manual_browser_evidence,
    canonical_evidence_timestamp,
    classify_public_page_context,
    sanitize_public_response_headers,
    validate_manual_browser_evidence,
)


KEY = "v0.59.15-local-test-signing-key"
HTML = f"""<!doctype html><html><head>
<meta charset="utf-8"><title>{EXPECTED_TITLE}</title>
<link rel="canonical" href="{EXPECTED_URL}">
<script src="/volatile.js" nonce="not-retained"></script>
</head><body class="page-id-8 stable"><h1>{EXPECTED_H1}</h1>
<img class="wp-image-31 hero" src="{EXPECTED_MEDIA_URL}?ver=1" alt="{EXPECTED_MEDIA_ALT}">
<p>Orlando service content.</p></body></html>"""
DUPLICATE_HTML = f"""<!doctype html><html><head>
<meta charset="utf-8"><title>{EXPECTED_TITLE}</title>
<link rel="canonical" href="{EXPECTED_URL}">
</head><body><main><h1 class="wp-block-post-title">{EXPECTED_H1}</h1>
<div class="entry-content wp-block-post-content"><h1>{EXPECTED_BODY_H1}</h1>
<img class="wp-image-31 hero" src="{EXPECTED_MEDIA_URL}" alt="{EXPECTED_MEDIA_ALT}">
<p>Orlando service content.</p></div></main></body></html>"""
PUBLIC_ADMIN_THEME_CSS = """<style>
:root { --wp-admin-theme-color:#007cba; --wp-admin-theme-color-darker-10:#006ba1;
--wp-admin-theme-color-darker-20:#005a87; }
.public-wp-admin-block-reference { color:var(--wp-admin-theme-color); }
</style>"""


def evidence(html: str = HTML, **kwargs):
    return build_manual_browser_evidence(
        html,
        final_url=EXPECTED_URL,
        evidence_identifier="orlando-evidence-001",
        signing_key=KEY,
        **kwargs,
    )


def resign(value: dict) -> dict:
    changed = json.loads(json.dumps(value))
    encoded = _canonical_json(_evidence_payload(changed))
    changed["helper_signature"] = hmac.new(KEY.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return changed


class StaticPublicClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_signed_browser_fallback_preserves_separate_sanitized_public_http_observation():
    signed = evidence()
    response = httpx.Response(
        200,
        request=httpx.Request("GET", EXPECTED_URL),
        headers={
            "Content-Type": "text/html; charset=UTF-8",
            "X-Cache-Enabled": "True",
            "X-Proxy-Cache": "HIT",
            "X-Proxy-Cache-Info": "DT:1",
            "Server": "nginx",
            "Set-Cookie": "wordpress_logged_in=secret",
        },
        text=HTML,
    )
    client = StaticPublicClient(response)
    result = acquire_rendered_state(
        "unused",
        "unused",
        manual_evidence=signed,
        evidence_signing_key=KEY,
        client=client,
    )
    assert len(client.calls) == 1
    assert result["source"] == "manual_browser_evidence"
    assert result["head_hash"] == signed["rendered_head_hash"]
    observation = result["public_http_observation"]
    assert observation["source"] == "public"
    assert observation["status_code"] == 200
    assert observation["redirect_count"] == 0
    assert observation["head_hash"] == signed["rendered_head_hash"]
    assert observation["visible_hash"] == signed["visible_content_hash"]
    assert observation["cache_headers"] == {
        "server": "nginx",
        "x-cache-enabled": "True",
        "x-proxy-cache": "HIT",
        "x-proxy-cache-info": "DT:1",
    }
    encoded = json.dumps(result).lower()
    assert "set-cookie" not in encoded
    assert "wordpress_logged_in" not in encoded


def test_public_header_sanitizer_preserves_repeats_and_rejects_secrets():
    assert sanitize_public_response_headers([
        ("Via", "proxy-a"),
        ("via", "proxy-b"),
        ("Authorization", "Basic secret"),
        ("Cookie", "secret"),
        ("Set-Cookie", "secret"),
    ]) == {"via": "proxy-a, proxy-b"}


def test_signed_timestamps_are_canonical_utc_with_fixed_microseconds():
    captured = datetime(2026, 7, 15, 3, 54, 43, 909827, tzinfo=UTC)
    value = evidence(captured_at=captured)
    assert value["captured_at"] == "2026-07-15T03:54:43.909827Z"
    assert value["expires_at"] == "2026-07-15T04:09:43.909827Z"
    assert CANONICAL_EVIDENCE_TIMESTAMP_PATTERN.fullmatch(value["captured_at"])
    assert CANONICAL_EVIDENCE_TIMESTAMP_PATTERN.fullmatch(value["expires_at"])


def test_timestamp_inputs_normalize_to_utc_before_signing():
    failed_shape = evidence(captured_at="2026-07-15T03:54:43.909827+00:00")
    canonical_shape = evidence(captured_at="2026-07-15T03:54:43.909827Z")
    local_shape = evidence(
        captured_at=datetime(
            2026,
            7,
            14,
            23,
            54,
            43,
            909827,
            tzinfo=timezone(timedelta(hours=-4)),
        )
    )
    assert failed_shape == canonical_shape == local_shape
    assert failed_shape["captured_at"] == "2026-07-15T03:54:43.909827Z"


def test_helper_evidence_survives_api_schema_round_trip():
    captured = datetime.now(UTC).replace(microsecond=0)
    value = evidence(DUPLICATE_HTML, schema_version=2, captured_at=captured)
    parsed = WordPressManualBrowserEvidence.model_validate(value)
    dumped = parsed.model_dump(mode="json", exclude_none=True)
    assert dumped == value
    assert dumped["captured_at"].endswith(".000000Z")
    assert validate_manual_browser_evidence(parsed, KEY) == (True, "Verified.")


def test_noncanonical_pre_fix_evidence_and_equivalent_raw_timestamp_are_rejected():
    captured = datetime.now(UTC).replace(microsecond=909827)
    canonical = evidence(captured_at=captured)
    equivalent_raw = json.loads(json.dumps(canonical))
    equivalent_raw["captured_at"] = equivalent_raw["captured_at"].replace("Z", "+00:00")
    equivalent_raw["expires_at"] = equivalent_raw["expires_at"].replace("Z", "+00:00")
    assert not validate_manual_browser_evidence(equivalent_raw, KEY)[0]

    pre_fix = json.loads(json.dumps(equivalent_raw))
    encoded = _canonical_json(_evidence_payload(pre_fix))
    pre_fix["helper_signature"] = hmac.new(KEY.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    assert validate_manual_browser_evidence(pre_fix, KEY) == (
        False,
        "Browser evidence timestamps are not canonical UTC strings.",
    )


def test_naive_malformed_tampered_and_invalid_lifetime_timestamps_are_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        evidence(captured_at=datetime(2026, 7, 15, 3, 54, 43, 909827))
    with pytest.raises(ValueError, match="timestamp is invalid"):
        canonical_evidence_timestamp("not-a-timestamp")

    captured = datetime.now(UTC).replace(microsecond=909827)
    value = evidence(captured_at=captured)
    tampered = json.loads(json.dumps(value))
    tampered["captured_at"] = canonical_evidence_timestamp(captured + timedelta(seconds=1))
    assert not validate_manual_browser_evidence(tampered, KEY)[0]

    invalid_lifetime = json.loads(json.dumps(value))
    invalid_lifetime["expires_at"] = canonical_evidence_timestamp(captured + timedelta(minutes=14))
    assert validate_manual_browser_evidence(resign(invalid_lifetime), KEY) == (
        False,
        "Browser evidence lifetime is invalid.",
    )


def test_versioned_contract_exact_identity_inventory_hashes_and_privacy():
    value = evidence()
    assert validate_manual_browser_evidence(value, KEY) == (True, "Verified.")
    assert value["evidence_schema"] == EVIDENCE_SCHEMA
    assert value["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION
    assert value["capture_helper_version"] == CAPTURE_HELPER_VERSION
    assert value["page_identity"] == {
        "document_title": EXPECTED_TITLE,
        "h1": EXPECTED_H1,
        "canonical_url": EXPECTED_URL,
        "featured_image_url": EXPECTED_MEDIA_URL,
        "featured_image_alt": EXPECTED_MEDIA_ALT,
    }
    inventory = value["metadata_inventory"]
    assert inventory["featured_image_references"] == [{"src": EXPECTED_MEDIA_URL, "alt": EXPECTED_MEDIA_ALT}]
    assert not inventory["open_graph"] and not inventory["twitter"] and not inventory["json_ld"]
    assert value["metadata_inventory_hash"] == hashlib.sha256(_canonical_json(inventory).encode()).hexdigest()
    assert value["rendered_head_hash"] == hashlib.sha256(value["normalized_head"].encode()).hexdigest()
    assert value["visible_content_hash"] == hashlib.sha256(value["normalized_visible_content"].encode()).hexdigest()
    assert value["privacy_attestations"] == {
        "credentials_used": False,
        "cookies_stored": False,
        "authorization_headers_stored": False,
        "authenticated_html_stored": False,
        "admin_session_used": False,
        "secrets_detected": False,
    }


def test_schema_v2_signs_locked_ordered_duplicate_h1_inventory():
    value = evidence(DUPLICATE_HTML, schema_version=2)
    assert validate_manual_browser_evidence(value, KEY) == (True, "Verified.")
    assert value["evidence_schema_version"] == EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1
    assert value["h1_count"] == 2
    assert value["primary_h1"] == EXPECTED_H1 and value["body_h1"] == EXPECTED_BODY_H1
    assert [item["text"] for item in value["h1_inventory"]] == [EXPECTED_H1, EXPECTED_BODY_H1]
    assert [item["ordinal"] for item in value["h1_inventory"]] == [1, 2]
    assert [item["source_classification"] for item in value["h1_inventory"]] == ["theme_owned_post_title", "atlas_body_content"]
    assert all(item["visible"] and item["dom_path"] for item in value["h1_inventory"])


def test_public_wordpress_admin_theme_css_is_accepted_with_safe_signed_diagnostics():
    public_html = HTML.replace("</head>", f"{PUBLIC_ADMIN_THEME_CSS}</head>")
    value = evidence(public_html)
    assert validate_manual_browser_evidence(value, KEY) == (True, "Verified.")
    assert value["navigation_outcome"] == {
        "status_code": 200,
        "content_type": "text/html",
        "redirect_count": 0,
        "outcome": "success",
        "admin_page_detected": False,
        "login_page_detected": False,
        "authenticated_context_detected": False,
        "challenge_page_detected": False,
        "error_page_detected": False,
        "admin_detection_signals": [],
    }


def test_orlando_duplicate_h1_fixture_with_public_admin_theme_css_is_accepted():
    public_html = DUPLICATE_HTML.replace("</head>", f"{PUBLIC_ADMIN_THEME_CSS}</head>")
    value = evidence(public_html, schema_version=2)
    assert validate_manual_browser_evidence(value, KEY) == (True, "Verified.")
    assert value["h1_count"] == 2


def test_legacy_schema_v1_navigation_outcome_retains_its_original_meaning():
    value = evidence()
    value["navigation_outcome"] = {"status_code": 200, "content_type": "text/html", "redirect_count": 0, "outcome": "success"}
    assert validate_manual_browser_evidence(resign(value), KEY) == (True, "Verified.")


def test_schema_v1_remains_one_h1_and_cannot_prove_duplicate_state():
    assert evidence()["evidence_schema_version"] == 1
    with pytest.raises(ValueError):
        evidence(DUPLICATE_HTML)
    captured = datetime(2026, 7, 14, tzinfo=UTC)
    assert evidence(HTML, schema_version=1, captured_at=captured) == evidence(HTML, captured_at=captured)


@pytest.mark.parametrize(
    "broken",
    [
        DUPLICATE_HTML.replace(f'<h1>{EXPECTED_BODY_H1}</h1>', ""),
        DUPLICATE_HTML.replace(EXPECTED_H1, "Wrong primary H1"),
        DUPLICATE_HTML.replace(EXPECTED_BODY_H1, "Wrong body H1"),
        DUPLICATE_HTML.replace(f'<h1>{EXPECTED_BODY_H1}</h1>', f'<h1 hidden>{EXPECTED_BODY_H1}</h1>'),
        DUPLICATE_HTML.replace(f'<h1>{EXPECTED_BODY_H1}</h1>', f'<h1>{EXPECTED_BODY_H1}</h1><h1>Third H1</h1>'),
        DUPLICATE_HTML.replace(
            f'<h1 class="wp-block-post-title">{EXPECTED_H1}</h1>\n<div class="entry-content wp-block-post-content"><h1>{EXPECTED_BODY_H1}</h1>',
            f'<div class="entry-content wp-block-post-content"><h1>{EXPECTED_BODY_H1}</h1></div><h1 class="wp-block-post-title">{EXPECTED_H1}</h1>\n<div class="entry-content wp-block-post-content">',
        ),
    ],
)
def test_schema_v2_rejects_wrong_count_text_visibility_or_order(broken: str):
    with pytest.raises(ValueError):
        evidence(broken, schema_version=2)


@pytest.mark.parametrize("field", ["dom_path", "source_classification"])
def test_schema_v2_inventory_tampering_invalidates_signature(field: str):
    value = evidence(DUPLICATE_HTML, schema_version=2)
    value["h1_inventory"][0][field] = "altered"
    assert not validate_manual_browser_evidence(value, KEY)[0]


def test_schema_v2_reordered_inventory_invalidates_signature_and_unknown_version_rejected():
    value = evidence(DUPLICATE_HTML, schema_version=2)
    value["h1_inventory"].reverse()
    assert not validate_manual_browser_evidence(value, KEY)[0]
    unknown = resign({**evidence(), "evidence_schema_version": 3})
    assert validate_manual_browser_evidence(unknown, KEY) == (False, "Browser evidence schema is unsupported.")


def test_schema_v2_expired_or_resigned_identity_mismatch_is_rejected():
    expired = evidence(DUPLICATE_HTML, schema_version=2, captured_at=datetime.now(UTC) - timedelta(minutes=16))
    assert not validate_manual_browser_evidence(expired, KEY)[0]
    mismatched = evidence(DUPLICATE_HTML, schema_version=2)
    mismatched["h1_inventory"][1]["text"] = "Mismatched body H1"
    assert not validate_manual_browser_evidence(resign(mismatched), KEY)[0]


@pytest.mark.parametrize(
    "broken",
    [
        HTML.replace(EXPECTED_TITLE, "Wrong title"),
        HTML.replace(EXPECTED_MEDIA_ALT, "Wrong alt"),
        HTML.replace(f'alt="{EXPECTED_MEDIA_ALT}"', ""),
        HTML.replace(f'<title>{EXPECTED_TITLE}</title>', f'<title>{EXPECTED_TITLE}</title><title>{EXPECTED_TITLE}</title>'),
        HTML.replace(f'<link rel="canonical" href="{EXPECTED_URL}">', f'<link rel="canonical" href="{EXPECTED_URL}"><link rel="canonical" href="{EXPECTED_URL}">'),
        HTML.replace("</head>", '<meta property="og:title" content="unexpected"></head>'),
        HTML.replace("</head>", '<meta name="twitter:card" content="summary"></head>'),
        HTML.replace("</head>", '<script type="application/ld+json">{"@type":"WebPage"}</script></head>'),
        HTML.replace("</body>", '<img class="wp-image-32" src="hero-1.png"></body>'),
        HTML.replace("</head>", '<meta name="description" data-project-atlas="metadata" content="unexpected"></head>'),
    ],
)
def test_wrong_identity_metadata_media32_and_duplicates_rejected(broken):
    with pytest.raises(ValueError):
        evidence(broken)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"credentials": "user:secret"},
        {"cookies": "wordpress_logged_in=value"},
        {"authorization_header": "Basic secret"},
        {"authenticated_html": True},
        {"admin_session_used": True},
    ],
)
def test_credential_cookie_authorization_and_authenticated_capture_rejected(kwargs):
    with pytest.raises(ValueError, match="forbidden"):
        evidence(**kwargs)


@pytest.mark.parametrize("marker", ["checking your browser", "captcha", "critical error", "template fallback"])
def test_challenge_error_and_fallback_pages_rejected(marker):
    with pytest.raises(ValueError):
        evidence(HTML + marker)


@pytest.mark.parametrize(
    ("final_url", "html", "expected_field", "expected_signal"),
    [
        ("https://www.drywoodtenting.com/wp-admin/", HTML, "admin_page_detected", "admin_url_path"),
        ("https://www.drywoodtenting.com/wp-login.php", HTML, "login_page_detected", None),
        (EXPECTED_URL, HTML.replace("</body>", '<form id="loginform" action="/wp-login.php"></form></body>'), "login_page_detected", None),
        (EXPECTED_URL, HTML.replace('<body class="page-id-8 stable">', '<body class="login wp-core-ui"><div id="login"><form id="loginform">'), "login_page_detected", None),
        (EXPECTED_URL, HTML.replace('<body class="page-id-8 stable">', '<body class="wp-admin wp-core-ui"><div id="wpwrap"><nav id="adminmenu"><a href="/wp-admin/">Dashboard</a></nav>'), "admin_page_detected", "admin_body_class"),
        (EXPECTED_URL, HTML.replace('class="page-id-8 stable"', 'class="wp-admin wp-core-ui"'), "admin_page_detected", "admin_body_class"),
        (EXPECTED_URL, HTML.replace(f'<title>{EXPECTED_TITLE}</title>', '<title>Dashboard ‹ My WordPress — WordPress</title>').replace('<body class="page-id-8 stable">', '<body><div id="wpwrap">'), "admin_page_detected", "dashboard_title_and_shell"),
        (EXPECTED_URL, HTML.replace('<body class="page-id-8 stable">', '<body class="logged-in admin-bar"><div id="wpadminbar">'), "admin_page_detected", "admin_toolbar_and_authenticated_context"),
    ],
)
def test_structural_admin_and_login_context_is_detected(final_url, html, expected_field, expected_signal):
    result = classify_public_page_context(html, final_url=final_url)
    assert result[expected_field] is True
    if expected_signal:
        assert expected_signal in result["admin_detection_signals"]
    with pytest.raises(ValueError):
        build_manual_browser_evidence(html, final_url=final_url, evidence_identifier="blocked-context", signing_key=KEY)


def test_authenticated_admin_toolbar_and_explicit_session_evidence_are_rejected():
    html = HTML.replace('<body class="page-id-8 stable">', '<body class="admin-bar"><div id="wpadminbar">')
    diagnostics = classify_public_page_context(html, final_url=EXPECTED_URL, admin_session_used=True)
    assert diagnostics["authenticated_context_detected"] is True
    assert diagnostics["admin_page_detected"] is True
    assert diagnostics["admin_detection_signals"] == ["admin_toolbar_and_authenticated_context"]
    with pytest.raises(ValueError, match="forbidden"):
        evidence(html, admin_session_used=True)


def test_resigned_false_safe_diagnostics_cannot_claim_admin_context_is_clear():
    value = evidence()
    value["navigation_outcome"]["admin_page_detected"] = True
    value["navigation_outcome"]["admin_detection_signals"] = ["admin_url_path"]
    assert not validate_manual_browser_evidence(resign(value), KEY)[0]


@pytest.mark.parametrize("marker", ["authorization: Bearer secret-material", "cookie: wordpress_logged_in=value", "wp_nonce=secret-value"])
def test_secret_bearing_source_content_remains_rejected(marker):
    with pytest.raises(ValueError, match="secret-bearing"):
        evidence(HTML + marker)


def test_wrong_url_redirect_content_type_and_status_rejected():
    with pytest.raises(ValueError):
        build_manual_browser_evidence(HTML, final_url="https://example.com/", evidence_identifier="wrong-url", signing_key=KEY)
    with pytest.raises(ValueError):
        evidence(redirect_count=1)
    with pytest.raises(ValueError):
        evidence(content_type="application/json")
    with pytest.raises(ValueError):
        evidence(status_code=403)


def test_missing_unsupported_schema_and_helper_rejected():
    value = evidence()
    missing = dict(value); missing.pop("evidence_schema")
    assert not validate_manual_browser_evidence(missing, KEY)[0]
    for field, replacement in (("evidence_schema", "unknown"), ("evidence_schema_version", 2), ("capture_helper_version", "future")):
        changed = resign({**value, field: replacement})
        assert not validate_manual_browser_evidence(changed, KEY)[0]


def test_signed_hard_coded_absence_and_hashes_cannot_bypass_inventory():
    value = evidence()
    changed = json.loads(json.dumps(value))
    changed["metadata_inventory"]["open_graph"] = [{"key": "og:title", "content": "hidden", "owner": ""}]
    changed["absence_findings"]["open_graph_absent"] = True
    changed["metadata_inventory_hash"] = hashlib.sha256(_canonical_json(changed["metadata_inventory"]).encode()).hexdigest()
    assert not validate_manual_browser_evidence(resign(changed), KEY)[0]
    for field in ("rendered_head_hash", "visible_content_hash", "metadata_inventory_hash"):
        altered = resign({**value, field: "0" * 64})
        assert not validate_manual_browser_evidence(altered, KEY)[0]


@pytest.mark.parametrize("field", [
    "evidence_id", "captured_at", "expires_at", "final_url", "acquisition_source", "navigation_outcome",
    "page_identity", "metadata_inventory", "metadata_inventory_hash", "absence_findings", "normalized_head",
    "normalized_visible_content", "rendered_head_hash", "visible_content_hash", "privacy_attestations",
])
def test_signature_covers_every_payload_field(field):
    value = evidence()
    changed = json.loads(json.dumps(value))
    changed[field] = "altered"
    assert not validate_manual_browser_evidence(changed, KEY)[0]


def test_expired_and_future_evidence_rejected():
    assert not validate_manual_browser_evidence(evidence(captured_at=datetime.now(UTC) - timedelta(minutes=16)), KEY)[0]
    assert not validate_manual_browser_evidence(evidence(captured_at=datetime.now(UTC) + timedelta(seconds=1)), KEY)[0]


def test_static_fixture_capture_helper_writes_only_signed_evidence(monkeypatch, tmp_path):
    fixture = tmp_path / "public-fixture.html"
    output = tmp_path / "signed-evidence.json"
    fixture.write_text(HTML, encoding="utf-8")
    monkeypatch.setenv("ATLAS_BROWSER_EVIDENCE_HMAC_KEY", KEY)
    monkeypatch.setattr(sys, "argv", ["capture_manual_browser_evidence.py", "--dry-run-fixture", str(fixture), "--output", str(output), "--evidence-id", "fixture-evidence-001"])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(Path(__file__).parents[1] / "scripts/capture_manual_browser_evidence.py"), run_name="__main__")
    assert result.value.code == 0
    written = json.loads(output.read_text(encoding="utf-8"))
    assert validate_manual_browser_evidence(written, KEY)[0]
    assert "<!doctype" not in output.read_text(encoding="utf-8").lower()
