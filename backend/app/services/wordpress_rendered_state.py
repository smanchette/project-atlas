from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import hmac
from html.parser import HTMLParser
import json
import re
import unicodedata
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx


EXPECTED_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
EXPECTED_MEDIA_URL = "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png"
EXPECTED_MEDIA_ALT = "Two-story Orlando Florida home professionally covered for drywood termite tenting"
EXPECTED_TITLE = "Drywood Termite Tenting in Orlando, FL \u2013 My WordPress"
EXPECTED_H1 = "Drywood Termite Tenting in Orlando, FL"
EVIDENCE_SCHEMA = "project-atlas-manual-browser-evidence"
EVIDENCE_SCHEMA_VERSION = 1
CAPTURE_HELPER_VERSION = "0.59.15"
EVIDENCE_LIFETIME = timedelta(minutes=15)
ACQUISITION_SOURCE = "credential_free_public_browser"
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
CHALLENGE_PATTERN = re.compile(r"cloudflare|captcha|access denied|bot protection|checking your browser|cf-chl", re.I)
ERROR_PATTERN = re.compile(r"wp-login\.php|wp-admin|critical error|error 404|page not found|template fallback|checking your browser", re.I)
CACHE_HEADERS = {"age", "cache-control", "cf-cache-status", "x-cache", "x-proxy-cache", "x-sg-cache"}
CACHE_BUSTING_QUERY_KEYS = {"_", "cb", "cache", "cachebust", "timestamp", "ver", "v"}
VOLATILE_ATTRIBUTES = {"nonce", "integrity", "crossorigin"}
WP_VOLATILE_TOKEN = re.compile(r"^(?:wp-|wp_|postid-|page-id-|page-template-|logged-in|admin-bar)", re.I)
MEDIA32_PATTERN = re.compile(r"(?:hero-1\.png|wp-image-32\b|/wp-json/wp/v2/media/32\b)", re.I)
ATLAS_MARKER_PATTERN = re.compile(r"(?:project atlas metadata bridge|data-project-atlas\s*=\s*[\"']metadata[\"'])", re.I)
INVENTORY_FIELDS = {
    "meta_descriptions", "canonicals", "open_graph", "twitter", "json_ld", "title_count", "canonical_count",
    "atlas_ownership_markers", "featured_image_references", "media32_references", "unexpected_metadata_owners", "duplicates",
}
ABSENCE_FIELDS = {
    "atlas_meta_description_absent", "open_graph_absent", "twitter_absent", "json_ld_absent", "media32_absent",
    "atlas_ownership_marker_absent", "duplicate_title_absent", "duplicate_canonical_absent",
}


def _text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _url(value: str) -> str:
    value = _text(value)
    try:
        parts = urlsplit(value)
        query = [(key, item) for key, item in parse_qsl(parts.query, keep_blank_values=True) if key.lower() not in CACHE_BUSTING_QUERY_KEYS]
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), parts.fragment))
    except ValueError:
        return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalize_attrs(attrs: list[tuple[str, str | None]]) -> list[tuple[str, str]]:
    normalized: list[tuple[str, str]] = []
    for raw_key, raw_value in attrs:
        key = raw_key.lower()
        if key in VOLATILE_ATTRIBUTES:
            continue
        value = _text(raw_value or "")
        if key in {"href", "src", "content"} and value.startswith(("http://", "https://")):
            value = _url(value)
        if key in {"id", "class"}:
            tokens = [token for token in value.split() if not WP_VOLATILE_TOKEN.match(token)]
            value = " ".join(sorted(tokens))
            if not value:
                continue
        normalized.append((key, value))
    return sorted(normalized)


class _EvidenceHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_head = False
        self.in_body = False
        self.ignored_depth = 0
        self.text_tag = ""
        self.text_parts: list[str] = []
        self.titles: list[str] = []
        self.h1: list[str] = []
        self.visible: list[str] = []
        self.meta_descriptions: list[dict[str, str]] = []
        self.canonicals: list[str] = []
        self.open_graph: list[dict[str, str]] = []
        self.twitter: list[dict[str, str]] = []
        self.json_ld: list[Any] = []
        self.images: list[dict[str, str]] = []
        self.ownership_markers: list[str] = []
        self.head_elements: list[dict[str, Any]] = []
        self.media32_references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): _text(value or "") for key, value in attrs}
        if tag == "head":
            self.in_head = True
        elif tag == "body":
            self.in_body = True
        if tag in {"script", "style", "noscript", "template"}:
            script_type = values.get("type", "").lower()
            if tag == "script" and script_type == "application/ld+json":
                self.text_tag = "json_ld"
                self.text_parts = []
            else:
                self.ignored_depth += 1
            return
        if tag in {"title", "h1"}:
            self.text_tag = tag
            self.text_parts = []
        if tag == "meta":
            key = _text(values.get("name") or values.get("property") or "").lower()
            content = _text(values.get("content", ""))
            owner = _text(values.get("data-project-atlas", ""))
            item = {"key": key, "content": content, "owner": owner}
            if key == "description":
                self.meta_descriptions.append(item)
            if key.startswith("og:"):
                self.open_graph.append(item)
            if key.startswith("twitter:"):
                self.twitter.append(item)
            if owner or "project-atlas" in _canonical_json(values).lower():
                self.ownership_markers.append(_canonical_json(item))
        if tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonicals.append(_url(values.get("href", "")))
        if tag == "img":
            image = {"src": _url(values.get("src", "")), "alt": _text(values.get("alt", ""))}
            self.images.append(image)
        encoded = _canonical_json(values)
        if tag != "meta" and ATLAS_MARKER_PATTERN.search(encoded):
            self.ownership_markers.append(f"{tag}:{encoded}")
        if MEDIA32_PATTERN.search(encoded):
            self.media32_references.append(f"{tag}:{encoded}")
        if self.in_head and tag not in {"html", "head"}:
            self.head_elements.append({"tag": tag, "attrs": _normalize_attrs(attrs)})

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "template"}:
            if tag == "script" and self.text_tag == "json_ld":
                source = _text(" ".join(self.text_parts))
                try:
                    self.json_ld.append(json.loads(source))
                except (TypeError, ValueError):
                    self.json_ld.append({"invalid_json_ld": source})
                self.text_tag = ""
                self.text_parts = []
            elif self.ignored_depth:
                self.ignored_depth -= 1
            return
        if tag == self.text_tag:
            value = _text(" ".join(self.text_parts))
            if tag == "title":
                self.titles.append(value)
            elif tag == "h1":
                self.h1.append(value)
            self.text_tag = ""
            self.text_parts = []
        if tag == "head":
            self.in_head = False
        elif tag == "body":
            self.in_body = False

    def handle_data(self, data: str) -> None:
        value = _text(data)
        if not value:
            return
        if self.text_tag:
            self.text_parts.append(value)
        if self.in_body and not self.ignored_depth:
            self.visible.append(value)
        if self.in_head and not self.ignored_depth and self.text_tag == "title":
            self.head_elements.append({"text": value})

    def handle_comment(self, data: str) -> None:
        value = _text(data)
        if ATLAS_MARKER_PATTERN.search(value):
            self.ownership_markers.append(value)
        if MEDIA32_PATTERN.search(value):
            self.media32_references.append(f"comment:{value}")


def _metadata_inventory(parsed: _EvidenceHTML) -> dict[str, Any]:
    featured = [image for image in parsed.images if image["src"] == EXPECTED_MEDIA_URL]
    duplicates: list[str] = []
    if len(parsed.titles) != 1:
        duplicates.append("title")
    if len(parsed.canonicals) != 1:
        duplicates.append("canonical")
    for label, entries in (("description", parsed.meta_descriptions), ("open_graph", parsed.open_graph), ("twitter", parsed.twitter)):
        keys = [item["key"] for item in entries]
        if len(keys) != len(set(keys)):
            duplicates.append(label)
    unexpected = []
    if parsed.meta_descriptions:
        unexpected.append("meta_description")
    if parsed.open_graph:
        unexpected.append("open_graph")
    if parsed.twitter:
        unexpected.append("twitter")
    if parsed.json_ld:
        unexpected.append("json_ld")
    if parsed.ownership_markers:
        unexpected.append("atlas_ownership_marker")
    return {
        "meta_descriptions": parsed.meta_descriptions,
        "canonicals": parsed.canonicals,
        "open_graph": parsed.open_graph,
        "twitter": parsed.twitter,
        "json_ld": parsed.json_ld,
        "title_count": len(parsed.titles),
        "canonical_count": len(parsed.canonicals),
        "atlas_ownership_markers": parsed.ownership_markers,
        "featured_image_references": featured,
        "media32_references": parsed.media32_references,
        "unexpected_metadata_owners": unexpected,
        "duplicates": duplicates,
    }


def _absence_findings(inventory: dict[str, Any]) -> dict[str, bool]:
    return {
        "atlas_meta_description_absent": not inventory["meta_descriptions"],
        "open_graph_absent": not inventory["open_graph"],
        "twitter_absent": not inventory["twitter"],
        "json_ld_absent": not inventory["json_ld"],
        "media32_absent": not inventory["media32_references"],
        "atlas_ownership_marker_absent": not inventory["atlas_ownership_markers"],
        "duplicate_title_absent": inventory["title_count"] == 1,
        "duplicate_canonical_absent": inventory["canonical_count"] == 1,
    }


def _privacy_attestations() -> dict[str, bool]:
    return {
        "credentials_used": False,
        "cookies_stored": False,
        "authorization_headers_stored": False,
        "authenticated_html_stored": False,
        "admin_session_used": False,
        "secrets_detected": False,
    }


def _evidence_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    return {key: evidence[key] for key in sorted(evidence) if key != "helper_signature"}


def build_manual_browser_evidence(
    html: str,
    *,
    final_url: str,
    evidence_identifier: str,
    signing_key: str,
    captured_at: datetime | None = None,
    status_code: int = 200,
    content_type: str = "text/html; charset=UTF-8",
    redirect_count: int = 0,
    credentials: str | None = None,
    cookies: str | None = None,
    authorization_header: str | None = None,
    authenticated_html: bool = False,
    admin_session_used: bool = False,
) -> dict[str, Any]:
    """Build evidence only from a credential-free public browser DOM capture."""
    if final_url != EXPECTED_URL or redirect_count != 0:
        raise ValueError("Browser evidence must use the locked Orlando URL without redirects.")
    if status_code != 200 or "text/html" not in content_type.lower():
        raise ValueError("Browser evidence navigation did not return a successful HTML document.")
    if credentials or cookies or authorization_header or authenticated_html or admin_session_used:
        raise ValueError("Credential-bearing or authenticated browser capture is forbidden.")
    if not signing_key:
        raise ValueError("A local browser-evidence signing key is required.")
    if SECRET_PATTERN.search(html) or SECRET_PATTERN.search(_canonical_json({"credentials": credentials, "cookies": cookies, "authorization": authorization_header})):
        raise ValueError("Browser evidence source contains secret-bearing content.")
    if CHALLENGE_PATTERN.search(html) or ERROR_PATTERN.search(html):
        raise ValueError("Challenge, login, admin, error, or fallback content cannot be evidence.")
    parsed = _EvidenceHTML()
    parsed.feed(html)
    inventory = _metadata_inventory(parsed)
    featured = inventory["featured_image_references"]
    if parsed.titles != [EXPECTED_TITLE] or parsed.h1 != [EXPECTED_H1] or parsed.canonicals != [EXPECTED_URL]:
        raise ValueError("Browser evidence does not match the locked title, H1, or canonical identity.")
    if featured != [{"src": EXPECTED_MEDIA_URL, "alt": EXPECTED_MEDIA_ALT}]:
        raise ValueError("Browser evidence featured-image URL or alt text is incorrect.")
    absence = _absence_findings(inventory)
    if not all(absence.values()) or inventory["unexpected_metadata_owners"] or inventory["duplicates"]:
        raise ValueError("Browser evidence contains metadata, duplicates, Atlas markers, or media 32.")
    captured = (captured_at or datetime.now(UTC)).astimezone(UTC)
    expires = captured + EVIDENCE_LIFETIME
    normalized_head = _canonical_json({"page": {"titles": parsed.titles, "canonicals": parsed.canonicals}, "head_elements": parsed.head_elements, "inventory": inventory})
    normalized_visible = _text(" ".join(parsed.visible))
    evidence: dict[str, Any] = {
        "evidence_schema": EVIDENCE_SCHEMA,
        "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
        "capture_helper_version": CAPTURE_HELPER_VERSION,
        "evidence_id": evidence_identifier,
        "captured_at": captured.isoformat(),
        "expires_at": expires.isoformat(),
        "final_url": final_url,
        "acquisition_source": ACQUISITION_SOURCE,
        "navigation_outcome": {"status_code": status_code, "content_type": content_type.split(";", 1)[0].lower(), "redirect_count": redirect_count, "outcome": "success"},
        "page_identity": {"document_title": parsed.titles[0], "h1": parsed.h1[0], "canonical_url": parsed.canonicals[0], "featured_image_url": featured[0]["src"], "featured_image_alt": featured[0]["alt"]},
        "metadata_inventory": inventory,
        "metadata_inventory_hash": _hash(_canonical_json(inventory)),
        "absence_findings": absence,
        "normalized_head": normalized_head,
        "normalized_visible_content": normalized_visible,
        "rendered_head_hash": _hash(normalized_head),
        "visible_content_hash": _hash(normalized_visible),
        "privacy_attestations": _privacy_attestations(),
    }
    encoded = _canonical_json(_evidence_payload(evidence))
    evidence["helper_signature"] = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return evidence


def validate_manual_browser_evidence(evidence: dict[str, Any] | Any | None, signing_key: str, *, now: datetime | None = None) -> tuple[bool, str]:
    if hasattr(evidence, "model_dump"):
        evidence = evidence.model_dump(mode="json")
    if not isinstance(evidence, dict) or not signing_key:
        return False, "Approved signed browser evidence is required."
    required = {
        "evidence_schema", "evidence_schema_version", "capture_helper_version", "evidence_id", "captured_at", "expires_at",
        "final_url", "acquisition_source", "navigation_outcome", "page_identity", "metadata_inventory", "metadata_inventory_hash",
        "absence_findings", "normalized_head", "normalized_visible_content", "rendered_head_hash", "visible_content_hash",
        "privacy_attestations", "helper_signature",
    }
    if set(evidence) != required:
        return False, "Browser evidence fields do not match the approved versioned helper format."
    if SECRET_PATTERN.search(_canonical_json(evidence)):
        return False, "Browser evidence contains secret-bearing content."
    if evidence.get("evidence_schema") != EVIDENCE_SCHEMA or evidence.get("evidence_schema_version") != EVIDENCE_SCHEMA_VERSION:
        return False, "Browser evidence schema is unsupported."
    if evidence.get("capture_helper_version") != CAPTURE_HELPER_VERSION or evidence.get("acquisition_source") != ACQUISITION_SOURCE:
        return False, "Browser evidence helper or acquisition source is unsupported."
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,199}", str(evidence.get("evidence_id", ""))):
        return False, "Browser evidence identifier is invalid."
    encoded = _canonical_json(_evidence_payload(evidence))
    expected_signature = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(evidence.get("helper_signature", "")), expected_signature):
        return False, "Browser evidence signature is invalid."
    try:
        captured = datetime.fromisoformat(str(evidence["captured_at"]))
        expires = datetime.fromisoformat(str(evidence["expires_at"]))
    except ValueError:
        return False, "Browser evidence timestamp is invalid."
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if captured.tzinfo is None or expires.tzinfo is None or expires.astimezone(UTC) - captured.astimezone(UTC) != EVIDENCE_LIFETIME:
        return False, "Browser evidence lifetime is invalid."
    if not captured.astimezone(UTC) <= current <= expires.astimezone(UTC):
        return False, "Browser evidence is expired or future-dated."
    navigation = evidence.get("navigation_outcome")
    if navigation != {"status_code": 200, "content_type": "text/html", "redirect_count": 0, "outcome": "success"}:
        return False, "Browser evidence navigation outcome is not an exact successful non-redirected HTML capture."
    identity = evidence.get("page_identity")
    if identity != {"document_title": EXPECTED_TITLE, "h1": EXPECTED_H1, "canonical_url": EXPECTED_URL, "featured_image_url": EXPECTED_MEDIA_URL, "featured_image_alt": EXPECTED_MEDIA_ALT} or evidence.get("final_url") != EXPECTED_URL:
        return False, "Browser evidence does not match the locked rendered-page identity."
    inventory = evidence.get("metadata_inventory")
    if not isinstance(inventory, dict) or set(inventory) != INVENTORY_FIELDS or evidence.get("metadata_inventory_hash") != _hash(_canonical_json(inventory)):
        return False, "Browser evidence metadata inventory hash is invalid."
    try:
        derived = _absence_findings(inventory)
    except (KeyError, TypeError):
        return False, "Browser evidence inventory is malformed."
    if not isinstance(evidence.get("absence_findings"), dict) or set(evidence["absence_findings"]) != ABSENCE_FIELDS or evidence.get("absence_findings") != derived or not all(derived.values()):
        return False, "Browser evidence absence findings do not match the signed inventory."
    if inventory.get("unexpected_metadata_owners") or inventory.get("duplicates") or inventory.get("featured_image_references") != [{"src": EXPECTED_MEDIA_URL, "alt": EXPECTED_MEDIA_ALT}]:
        return False, "Browser evidence inventory contains unexpected or duplicate rendered state."
    if evidence.get("privacy_attestations") != _privacy_attestations():
        return False, "Browser evidence privacy attestations are invalid."
    normalized_head = evidence.get("normalized_head", "")
    normalized_visible = evidence.get("normalized_visible_content", "")
    if not isinstance(normalized_head, str) or not isinstance(normalized_visible, str) or evidence.get("rendered_head_hash") != _hash(normalized_head) or evidence.get("visible_content_hash") != _hash(normalized_visible):
        return False, "Browser evidence rendered hashes do not recompute."
    try:
        head_payload = json.loads(normalized_head)
    except (TypeError, ValueError):
        return False, "Browser evidence normalized head is malformed."
    if head_payload.get("page") != {"titles": [EXPECTED_TITLE], "canonicals": [EXPECTED_URL]} or head_payload.get("inventory") != inventory or not isinstance(head_payload.get("head_elements"), list):
        return False, "Browser evidence normalized head is not bound to the signed identity and inventory."
    if not normalized_head or not normalized_visible:
        return False, "Browser evidence normalized rendered payload is empty."
    return True, "Verified."


def _html_result(response: httpx.Response, outcome: str, source: str) -> dict[str, Any]:
    final_url = str(response.url)
    headers = {key.lower(): value for key, value in response.headers.items()}
    base: dict[str, Any] = {"source": source, "outcome": outcome, "final_url": final_url, "status_code": response.status_code, "content_type": headers.get("content-type", ""), "cache_headers": {key: value for key, value in headers.items() if key in CACHE_HEADERS}, "verified": False}
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
    parsed = _EvidenceHTML()
    parsed.feed(body)
    featured = [image for image in parsed.images if image["src"] == EXPECTED_MEDIA_URL]
    inventory = _metadata_inventory(parsed)
    absence = _absence_findings(inventory)
    identity_ok = parsed.titles == [EXPECTED_TITLE] and parsed.h1 == [EXPECTED_H1] and parsed.canonicals == [EXPECTED_URL] and featured == [{"src": EXPECTED_MEDIA_URL, "alt": EXPECTED_MEDIA_ALT}] and all(absence.values()) and not inventory["unexpected_metadata_owners"] and not inventory["duplicates"]
    if not identity_ok:
        return {**base, "outcome": "error_page_detected"}
    normalized_head = _canonical_json({"page": {"titles": parsed.titles, "canonicals": parsed.canonicals}, "head_elements": parsed.head_elements, "inventory": inventory})
    normalized_visible = _text(" ".join(parsed.visible))
    return {**base, "outcome": outcome, "verified": True, "head_hash": _hash(normalized_head), "visible_hash": _hash(normalized_visible), "document_title": parsed.titles, "h1": parsed.h1, "canonical": parsed.canonicals, "featured_image_url": EXPECTED_MEDIA_URL, "featured_image_alt": EXPECTED_MEDIA_ALT, "atlas_metadata_marker_present": bool(inventory["atlas_ownership_markers"]), "media32_reference_present": bool(inventory["media32_references"])}


def acquire_rendered_state(username: str, password: str, *, manual_evidence: dict[str, Any] | Any | None = None, evidence_signing_key: str = "", verified_bypass_url: str = "", bypass_independently_verified: bool = False, client: httpx.Client | None = None) -> dict[str, Any]:
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
        if hasattr(manual_evidence, "model_dump"):
            manual_evidence = manual_evidence.model_dump(mode="json")
        identity = manual_evidence["page_identity"]
        absence = manual_evidence["absence_findings"]
        return {"source": "manual_browser_evidence", "outcome": "manual_browser_evidence_verified", "verified": True, "final_url": EXPECTED_URL, "head_hash": manual_evidence["rendered_head_hash"], "visible_hash": manual_evidence["visible_content_hash"], "document_title": [identity["document_title"]], "h1": [identity["h1"]], "canonical": [identity["canonical_url"]], "featured_image_url": identity["featured_image_url"], "featured_image_alt": identity["featured_image_alt"], "browser_evidence_identifier": manual_evidence["evidence_id"], "evidence_schema": manual_evidence["evidence_schema"], "evidence_schema_version": manual_evidence["evidence_schema_version"], "capture_helper_version": manual_evidence["capture_helper_version"], "evidence_timestamp": manual_evidence["captured_at"], "evidence_expires_at": manual_evidence["expires_at"], "metadata_inventory": manual_evidence["metadata_inventory"], "metadata_inventory_hash": manual_evidence["metadata_inventory_hash"], "privacy_attestations": manual_evidence["privacy_attestations"], "signature_validated": True, "atlas_metadata_marker_present": not absence["atlas_ownership_marker_absent"], "media32_reference_present": not absence["media32_absent"], "cache_headers": {}}
    if public_result and public_result.get("outcome") == "bot_protection_blocked":
        result = public_result
    return {**result, "manual_evidence_outcome": "manual_browser_evidence_required", "manual_evidence_reason": reason, "verified": False}
