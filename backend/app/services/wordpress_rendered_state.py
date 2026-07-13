from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from html.parser import HTMLParser
import json
import re
from typing import Any

import httpx

from app.services.wordpress_metadata import _parse_html


EXPECTED_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
EXPECTED_MEDIA_URL = "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png"
EXPECTED_TITLE = "Drywood Termite Tenting in Orlando, FL"
EXPECTED_H1 = "Drywood Termite Tenting in Orlando, FL"
VERIFIED_OUTCOMES = {
    "public_html_verified",
    "authenticated_html_verified",
    "cache_bypass_verified",
    "manual_browser_evidence_verified",
}
SECRET_PATTERN = re.compile(
    r"(?:authorization\s*:|cookie\s*:|set-cookie\s*:|application[_ -]?password|wp[_-]?nonce|password\s*[=:])",
    re.I,
)
BOT_PATTERN = re.compile(r"cloudflare|siteground|captcha|access denied|bot protection|checking your browser|cf-chl", re.I)
ERROR_PATTERN = re.compile(r"wp-login\.php|critical error|error 404|page not found|template fallback|checking your browser", re.I)
CACHE_HEADERS = {"age", "cache-control", "cf-cache-status", "x-cache", "x-proxy-cache", "x-sg-cache"}


class _EvidenceHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.images: list[str] = []
        self.metadata: list[dict[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "img" and values.get("src"):
            self.images.append(str(values["src"]))
        if tag == "meta":
            self.metadata.append({key: values.get(key) for key in ("name", "property", "content")})


def _safe_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _evidence_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {key: evidence[key] for key in sorted(evidence) if key != "helper_signature"}


def build_manual_browser_evidence(
    html: str,
    *,
    final_url: str,
    evidence_identifier: str,
    signing_key: str,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    if final_url != EXPECTED_URL:
        raise ValueError("Browser evidence final URL is not the locked Orlando URL.")
    if not signing_key:
        raise ValueError("A local browser-evidence signing key is required.")
    if SECRET_PATTERN.search(html):
        raise ValueError("Browser evidence source contains secret-bearing content.")
    parsed = _parse_html(html)
    extra = _EvidenceHTML()
    extra.feed(html)
    if parsed.get("titles") is None or parsed.get("h1") is None:
        raise ValueError("Browser evidence HTML could not be parsed.")
    evidence: dict[str, Any] = {
        "expected_final_url": final_url,
        "document_title": parsed.get("titles", []),
        "h1": parsed.get("h1", []),
        "canonical": parsed.get("canonicals", []),
        "featured_image_url": EXPECTED_MEDIA_URL if EXPECTED_MEDIA_URL in extra.images or EXPECTED_MEDIA_URL in html else "",
        "metadata_inventory_hash": _safe_hash(json.dumps(extra.metadata, sort_keys=True, separators=(",", ":"))),
        "visible_content_hash": parsed.get("visible_hash", ""),
        "rendered_head_hash": parsed.get("head_hash", ""),
        "evidence_timestamp": (captured_at or datetime.now(UTC)).astimezone(UTC).isoformat(),
        "browser_evidence_identifier": evidence_identifier,
    }
    encoded = json.dumps(_evidence_payload(evidence), sort_keys=True, separators=(",", ":"))
    evidence["helper_signature"] = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return evidence


def validate_manual_browser_evidence(
    evidence: dict[str, Any] | None,
    signing_key: str,
    *,
    now: datetime | None = None,
) -> tuple[bool, str]:
    if not evidence or not signing_key:
        return False, "Approved signed browser evidence is required."
    if SECRET_PATTERN.search(json.dumps(evidence, sort_keys=True)):
        return False, "Browser evidence contains secret-bearing content."
    required = {
        "expected_final_url", "document_title", "h1", "canonical", "featured_image_url",
        "metadata_inventory_hash", "visible_content_hash", "rendered_head_hash",
        "evidence_timestamp", "browser_evidence_identifier", "helper_signature",
    }
    if set(evidence) != required:
        return False, "Browser evidence fields do not match the approved helper format."
    encoded = json.dumps(_evidence_payload(evidence), sort_keys=True, separators=(",", ":"))
    signature = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(evidence["helper_signature"]), signature):
        return False, "Browser evidence signature is invalid."
    try:
        timestamp = datetime.fromisoformat(str(evidence["evidence_timestamp"]))
    except ValueError:
        return False, "Browser evidence timestamp is invalid."
    current = now or datetime.now(UTC)
    if timestamp.tzinfo is None or not timedelta(0) <= current.astimezone(UTC) - timestamp.astimezone(UTC) <= timedelta(minutes=15):
        return False, "Browser evidence is expired or future-dated."
    hash_pattern = re.compile(r"[0-9a-f]{64}")
    if (
        evidence["expected_final_url"] != EXPECTED_URL
        or evidence["canonical"] != [EXPECTED_URL]
        or evidence["document_title"] != [EXPECTED_TITLE]
        or evidence["h1"] != [EXPECTED_H1]
        or evidence["featured_image_url"] != EXPECTED_MEDIA_URL
        or not all(hash_pattern.fullmatch(str(evidence[key])) for key in ("metadata_inventory_hash", "visible_content_hash", "rendered_head_hash"))
    ):
        return False, "Browser evidence does not match the locked rendered-page identity."
    return True, "Verified."


def _html_result(response: httpx.Response, outcome: str, source: str) -> dict[str, Any]:
    final_url = str(response.url)
    headers = {key.lower(): value for key, value in response.headers.items()}
    base: dict[str, Any] = {
        "source": source,
        "outcome": outcome,
        "final_url": final_url,
        "status_code": response.status_code,
        "content_type": headers.get("content-type", ""),
        "cache_headers": {key: value for key, value in headers.items() if key in CACHE_HEADERS},
        "verified": False,
    }
    body = response.text
    if 300 <= response.status_code < 400 or final_url != EXPECTED_URL:
        return {**base, "outcome": "unexpected_redirect"}
    if response.status_code == 403 and BOT_PATTERN.search(body + " " + " ".join(headers.values())):
        return {**base, "outcome": "bot_protection_blocked"}
    if response.status_code in {404, 500, 502, 503, 504}:
        return {**base, "outcome": "error_page_detected"}
    if response.status_code >= 400:
        return {**base, "outcome": "unavailable"}
    if "text/html" not in headers.get("content-type", "").lower() or ERROR_PATTERN.search(body):
        return {**base, "outcome": "error_page_detected"}
    parsed = _parse_html(body)
    encoded = json.dumps(parsed, sort_keys=True)
    identity_ok = (
        parsed.get("titles") == [EXPECTED_TITLE]
        and parsed.get("h1") == [EXPECTED_H1]
        and parsed.get("canonicals") == [EXPECTED_URL]
        and EXPECTED_MEDIA_URL in body
        and bool(parsed.get("head_hash"))
        and bool(parsed.get("visible_hash"))
    )
    if not identity_ok:
        return {**base, "outcome": "error_page_detected"}
    return {
        **base,
        "outcome": outcome,
        "verified": True,
        "head_hash": parsed["head_hash"],
        "visible_hash": parsed["visible_hash"],
        "raw_hash": parsed["raw_hash"],
        "document_title": parsed["titles"],
        "h1": parsed["h1"],
        "canonical": parsed["canonicals"],
        "featured_image_url": EXPECTED_MEDIA_URL,
        "atlas_metadata_marker_present": "data-project-atlas=\"metadata\"" in body or "Project Atlas Metadata Bridge" in body,
        "media32_reference_present": "hero-1.png" in encoded or "hero-1.png" in body,
    }


def acquire_rendered_state(
    username: str,
    password: str,
    *,
    manual_evidence: dict[str, Any] | None = None,
    evidence_signing_key: str = "",
    verified_bypass_url: str = "",
    bypass_independently_verified: bool = False,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    owned = client is None
    browser = client or httpx.Client(timeout=15, follow_redirects=False)
    result: dict[str, Any]
    try:
        routes: list[tuple[str, str, Any]] = []
        if verified_bypass_url and bypass_independently_verified:
            routes.append((verified_bypass_url, "cache_bypass_verified", None))
        routes.append((EXPECTED_URL, "public_html_verified", None))
        routes.append((EXPECTED_URL, "authenticated_html_verified", httpx.BasicAuth(username, password)))
        result = {"source": "none", "outcome": "unavailable", "verified": False}
        public_result: dict[str, Any] | None = None
        for url, outcome, auth in routes:
            if url != EXPECTED_URL:
                result = {"source": "cache_bypass", "outcome": "unexpected_redirect", "verified": False}
                break
            try:
                response = browser.get(url, auth=auth, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            except httpx.HTTPError:
                result = {"source": "authenticated" if auth else "public", "outcome": "network_failed", "verified": False}
                continue
            source = "cache_bypass" if outcome == "cache_bypass_verified" else ("authenticated" if auth else "public")
            candidate = _html_result(response, outcome, source)
            if source == "public":
                public_result = candidate
            if candidate.get("verified"):
                return candidate
            result = candidate
    finally:
        if owned:
            browser.close()

    valid, reason = validate_manual_browser_evidence(manual_evidence, evidence_signing_key)
    if valid and manual_evidence:
        return {
            "source": "manual_browser_evidence",
            "outcome": "manual_browser_evidence_verified",
            "verified": True,
            "final_url": EXPECTED_URL,
            "head_hash": manual_evidence["rendered_head_hash"],
            "visible_hash": manual_evidence["visible_content_hash"],
            "document_title": manual_evidence["document_title"],
            "h1": manual_evidence["h1"],
            "canonical": manual_evidence["canonical"],
            "featured_image_url": manual_evidence["featured_image_url"],
            "browser_evidence_identifier": manual_evidence["browser_evidence_identifier"],
            "atlas_metadata_marker_present": False,
            "media32_reference_present": False,
            "cache_headers": {},
        }
    if public_result and public_result.get("outcome") == "bot_protection_blocked":
        result = public_result
    return {**result, "manual_evidence_outcome": "manual_browser_evidence_required", "manual_evidence_reason": reason, "verified": False}
