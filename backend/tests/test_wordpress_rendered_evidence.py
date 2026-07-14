from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from pathlib import Path
import runpy
import sys

import pytest

from app.services.wordpress_rendered_state import (
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
    build_manual_browser_evidence,
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


@pytest.mark.parametrize("marker", ["wp-login.php", "/wp-admin/", "checking your browser", "captcha", "critical error", "template fallback"])
def test_login_admin_challenge_error_and_fallback_pages_rejected(marker):
    with pytest.raises(ValueError):
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
