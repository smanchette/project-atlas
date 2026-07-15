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
EXPECTED_BODY_H1 = "Drywood Termite Tenting in Orlando, Florida"
EVIDENCE_SCHEMA = "project-atlas-manual-browser-evidence"
EVIDENCE_SCHEMA_VERSION = 1
EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1 = 2
CAPTURE_HELPER_VERSION = "0.59.15"
EVIDENCE_LIFETIME = timedelta(minutes=15)
CANONICAL_EVIDENCE_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$"
)
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
ERROR_PATTERN = re.compile(r"critical error|error 404|page not found|template fallback|checking your browser", re.I)
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


def _parse_evidence_timestamp(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError as exc:
            raise ValueError("Browser evidence timestamp is invalid.") from exc
    else:
        raise ValueError("Browser evidence timestamp is invalid.")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Browser evidence timestamp must be timezone-aware.")
    return parsed.astimezone(UTC)


def canonical_evidence_timestamp(value: datetime | str) -> str:
    """Return the sole timestamp representation permitted in signed evidence."""
    return _parse_evidence_timestamp(value).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonicalized_evidence_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    payload = _evidence_payload(evidence)
    payload["captured_at"] = canonical_evidence_timestamp(payload["captured_at"])
    payload["expires_at"] = canonical_evidence_timestamp(payload["expires_at"])
    return payload


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


class _PublicPageContextHTML(HTMLParser):
    """Collect structural login/admin signals without inspecting stylesheet text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.body_classes: set[str] = set()
        self.element_classes: set[str] = set()
        self.element_ids: set[str] = set()
        self.form_actions: list[str] = []
        self.hrefs: list[str] = []
        self.in_title = False
        self.title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): _text(value or "") for key, value in attrs}
        classes = {item.lower() for item in values.get("class", "").split()}
        self.element_classes.update(classes)
        if tag == "body":
            self.body_classes.update(classes)
        if values.get("id"):
            self.element_ids.add(values["id"].lower())
        if tag == "form" and values.get("action"):
            self.form_actions.append(values["action"])
        if values.get("href"):
            self.hrefs.append(values["href"])
        if tag == "title":
            self.in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)


def classify_public_page_context(
    html: str,
    *,
    final_url: str,
    status_code: int = 200,
    credentials: str | None = None,
    cookies: str | None = None,
    authorization_header: str | None = None,
    authenticated_html: bool = False,
    admin_session_used: bool = False,
) -> dict[str, Any]:
    """Return safe structural page-context diagnostics without retaining raw HTML."""

    parsed = _PublicPageContextHTML()
    parsed.feed(html)
    parsed.close()
    def safe_path(value: str) -> str:
        try:
            return urlsplit(value).path.lower()
        except ValueError:
            return ""

    path = safe_path(final_url)
    normalized_path = path.rstrip("/") or "/"
    login_url = normalized_path == "/wp-login.php"
    admin_url = normalized_path == "/wp-admin" or path.startswith("/wp-admin/")
    login_form = any((safe_path(action).rstrip("/") or "/") == "/wp-login.php" for action in parsed.form_actions)
    login_shell = "loginform" in parsed.element_ids or "login" in parsed.element_ids
    login_body = "login" in parsed.body_classes and login_shell
    title = _text(" ".join(parsed.title_parts)).lower()
    login_title = ("log in" in title or "login" in title) and "wordpress" in title and (login_form or login_shell)

    admin_shell_ids = {"wpwrap", "wpcontent", "wpbody", "wpbody-content", "adminmenu", "adminmenuwrap"}
    admin_shell = bool(parsed.element_ids & admin_shell_ids)
    admin_body = "wp-admin" in parsed.body_classes and ("wp-core-ui" in parsed.body_classes or admin_shell)
    dashboard_title = ("dashboard" in title and "wordpress" in title) and admin_shell
    admin_links = any(
        (safe_path(href).rstrip("/") or "/") == "/wp-admin"
        or safe_path(href).startswith("/wp-admin/")
        for href in parsed.hrefs
    )
    toolbar = "wpadminbar" in parsed.element_ids or "admin-bar" in parsed.body_classes
    authenticated_context = bool(
        credentials
        or cookies
        or authorization_header
        or authenticated_html
        or admin_session_used
        or "logged-in" in parsed.body_classes
    )
    admin_signals: list[str] = []
    if admin_url:
        admin_signals.append("admin_url_path")
    if admin_body:
        admin_signals.append("admin_body_class")
    if dashboard_title:
        admin_signals.append("dashboard_title_and_shell")
    if admin_links and admin_shell:
        admin_signals.append("admin_navigation_and_shell")
    if toolbar and authenticated_context:
        admin_signals.append("admin_toolbar_and_authenticated_context")
    admin_detected = bool(admin_signals)
    return {
        "admin_page_detected": admin_detected,
        "login_page_detected": bool(login_url or login_form or login_body or login_title),
        "authenticated_context_detected": authenticated_context,
        "challenge_page_detected": bool(CHALLENGE_PATTERN.search(html)),
        "error_page_detected": bool(status_code in {404, 500, 502, 503, 504} or ERROR_PATTERN.search(html)),
        "admin_detection_signals": admin_signals,
    }


class _H1InventoryHTML(HTMLParser):
    """Collect a deterministic, ordered H1 inventory without changing schema-v1 parsing."""

    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[dict[str, Any]] = []
        self.root_counts: dict[str, int] = {}
        self.inventory: list[dict[str, Any]] = []
        self.active_h1: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        values = {key.lower(): _text(value or "") for key, value in attrs}
        counts = self.stack[-1]["child_counts"] if self.stack else self.root_counts
        counts[tag] = counts.get(tag, 0) + 1
        segment = f"{tag}:nth-of-type({counts[tag]})"
        parent_path = self.stack[-1]["path"] if self.stack else ""
        path = f"{parent_path}>{segment}" if parent_path else segment
        classes = sorted(set(values.get("class", "").split()))
        ancestor_classes = sorted({item for frame in self.stack for item in frame["classes"]})
        hidden_here = (
            "hidden" in values
            or values.get("aria-hidden", "").lower() == "true"
            or bool({"hidden", "is-hidden", "screen-reader-text", "sr-only", "visually-hidden"} & {item.lower() for item in classes})
            or bool(re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", values.get("style", ""), re.I))
        )
        visible = not hidden_here and all(frame["visible"] for frame in self.stack)
        frame = {"tag": tag, "path": path, "classes": classes, "visible": visible, "child_counts": {}}
        if tag == "h1":
            self.active_h1 = {
                "text_parts": [],
                "ordinal": len(self.inventory) + 1,
                "dom_path": path,
                "classes": classes,
                "ancestor_classes": ancestor_classes,
                "visible": visible,
            }
        if tag not in self._VOID:
            self.stack.append(frame)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "h1" and self.active_h1 is not None:
            text_parts = self.active_h1.pop("text_parts")
            entry = {**self.active_h1, "text": _text(" ".join(text_parts))}
            entry["source_classification"] = _classify_h1(entry)
            self.inventory.append(entry)
            self.active_h1 = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self.active_h1 is not None:
            self.active_h1["text_parts"].append(data)


def _classify_h1(entry: dict[str, Any]) -> str:
    classes = set(entry.get("classes", []))
    ancestors = set(entry.get("ancestor_classes", []))
    if entry.get("text") == EXPECTED_H1 and "wp-block-post-title" in classes:
        return "theme_owned_post_title"
    if entry.get("text") == EXPECTED_BODY_H1 and {"entry-content", "wp-block-post-content"} & ancestors:
        return "atlas_body_content"
    return "unclassified"


def _ordered_h1_inventory(html: str) -> list[dict[str, Any]]:
    parser = _H1InventoryHTML()
    parser.feed(html)
    parser.close()
    return parser.inventory


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
    captured_at: datetime | str | None = None,
    status_code: int = 200,
    content_type: str = "text/html; charset=UTF-8",
    redirect_count: int = 0,
    credentials: str | None = None,
    cookies: str | None = None,
    authorization_header: str | None = None,
    authenticated_html: bool = False,
    admin_session_used: bool = False,
    schema_version: int = EVIDENCE_SCHEMA_VERSION,
) -> dict[str, Any]:
    """Build evidence only from a credential-free public browser DOM capture."""
    context = classify_public_page_context(
        html,
        final_url=final_url,
        status_code=status_code,
        credentials=credentials,
        cookies=cookies,
        authorization_header=authorization_header,
        authenticated_html=authenticated_html,
        admin_session_used=admin_session_used,
    )
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
    if any(context[field] for field in ("admin_page_detected", "login_page_detected", "authenticated_context_detected", "challenge_page_detected", "error_page_detected")):
        raise ValueError("Challenge, login, admin, error, or fallback content cannot be evidence.")
    parsed = _EvidenceHTML()
    parsed.feed(html)
    inventory = _metadata_inventory(parsed)
    featured = inventory["featured_image_references"]
    if schema_version not in {EVIDENCE_SCHEMA_VERSION, EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1}:
        raise ValueError("Browser evidence schema is unsupported.")
    expected_h1 = [EXPECTED_H1] if schema_version == 1 else [EXPECTED_H1, EXPECTED_BODY_H1]
    if parsed.titles != [EXPECTED_TITLE] or parsed.h1 != expected_h1 or parsed.canonicals != [EXPECTED_URL]:
        raise ValueError("Browser evidence does not match the locked title, H1, or canonical identity.")
    if featured != [{"src": EXPECTED_MEDIA_URL, "alt": EXPECTED_MEDIA_ALT}]:
        raise ValueError("Browser evidence featured-image URL or alt text is incorrect.")
    absence = _absence_findings(inventory)
    if not all(absence.values()) or inventory["unexpected_metadata_owners"] or inventory["duplicates"]:
        raise ValueError("Browser evidence contains metadata, duplicates, Atlas markers, or media 32.")
    captured = _parse_evidence_timestamp(captured_at or datetime.now(UTC))
    expires = captured + EVIDENCE_LIFETIME
    normalized_head = _canonical_json({"page": {"titles": parsed.titles, "canonicals": parsed.canonicals}, "head_elements": parsed.head_elements, "inventory": inventory})
    normalized_visible = _text(" ".join(parsed.visible))
    evidence: dict[str, Any] = {
        "evidence_schema": EVIDENCE_SCHEMA,
        "evidence_schema_version": schema_version,
        "capture_helper_version": CAPTURE_HELPER_VERSION,
        "evidence_id": evidence_identifier,
        "captured_at": canonical_evidence_timestamp(captured),
        "expires_at": canonical_evidence_timestamp(expires),
        "final_url": final_url,
        "acquisition_source": ACQUISITION_SOURCE,
        "navigation_outcome": {
            "status_code": status_code,
            "content_type": content_type.split(";", 1)[0].lower(),
            "redirect_count": redirect_count,
            "outcome": "success",
            **context,
        },
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
    if schema_version == EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1:
        h1_inventory = _ordered_h1_inventory(html)
        if not _valid_duplicate_h1_inventory(h1_inventory):
            raise ValueError("Browser evidence does not contain the locked visible duplicate-H1 inventory.")
        evidence.update(
            {
                "h1_inventory": h1_inventory,
                "h1_count": len(h1_inventory),
                "primary_h1": EXPECTED_H1,
                "body_h1": EXPECTED_BODY_H1,
            }
        )
    encoded = _canonical_json(_canonicalized_evidence_payload(evidence))
    evidence["helper_signature"] = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    return evidence


def validate_manual_browser_evidence(evidence: dict[str, Any] | Any | None, signing_key: str, *, now: datetime | None = None) -> tuple[bool, str]:
    if hasattr(evidence, "model_dump"):
        evidence = evidence.model_dump(mode="json", exclude_none=True)
    if not isinstance(evidence, dict) or not signing_key:
        return False, "Approved signed browser evidence is required."
    required_v1 = {
        "evidence_schema", "evidence_schema_version", "capture_helper_version", "evidence_id", "captured_at", "expires_at",
        "final_url", "acquisition_source", "navigation_outcome", "page_identity", "metadata_inventory", "metadata_inventory_hash",
        "absence_findings", "normalized_head", "normalized_visible_content", "rendered_head_hash", "visible_content_hash",
        "privacy_attestations", "helper_signature",
    }
    version = evidence.get("evidence_schema_version")
    if version not in {EVIDENCE_SCHEMA_VERSION, EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1}:
        return False, "Browser evidence schema is unsupported."
    required = required_v1 if version == 1 else required_v1 | {"h1_inventory", "h1_count", "primary_h1", "body_h1"}
    if set(evidence) != required:
        return False, "Browser evidence fields do not match the approved versioned helper format."
    if SECRET_PATTERN.search(_canonical_json(evidence)):
        return False, "Browser evidence contains secret-bearing content."
    if evidence.get("evidence_schema") != EVIDENCE_SCHEMA:
        return False, "Browser evidence schema is unsupported."
    if evidence.get("capture_helper_version") != CAPTURE_HELPER_VERSION or evidence.get("acquisition_source") != ACQUISITION_SOURCE:
        return False, "Browser evidence helper or acquisition source is unsupported."
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{7,199}", str(evidence.get("evidence_id", ""))):
        return False, "Browser evidence identifier is invalid."
    try:
        captured_text = canonical_evidence_timestamp(evidence["captured_at"])
        expires_text = canonical_evidence_timestamp(evidence["expires_at"])
    except (KeyError, ValueError):
        return False, "Browser evidence timestamp is invalid."
    if (
        not isinstance(evidence.get("captured_at"), str)
        or not isinstance(evidence.get("expires_at"), str)
        or not CANONICAL_EVIDENCE_TIMESTAMP_PATTERN.fullmatch(evidence["captured_at"])
        or not CANONICAL_EVIDENCE_TIMESTAMP_PATTERN.fullmatch(evidence["expires_at"])
        or evidence["captured_at"] != captured_text
        or evidence["expires_at"] != expires_text
    ):
        return False, "Browser evidence timestamps are not canonical UTC strings."
    encoded = _canonical_json(_canonicalized_evidence_payload(evidence))
    expected_signature = hmac.new(signing_key.encode(), encoded.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(evidence.get("helper_signature", "")), expected_signature):
        return False, "Browser evidence signature is invalid."
    captured = _parse_evidence_timestamp(captured_text)
    expires = _parse_evidence_timestamp(expires_text)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if captured.tzinfo is None or expires.tzinfo is None or expires.astimezone(UTC) - captured.astimezone(UTC) != EVIDENCE_LIFETIME:
        return False, "Browser evidence lifetime is invalid."
    if not captured.astimezone(UTC) <= current <= expires.astimezone(UTC):
        return False, "Browser evidence is expired or future-dated."
    navigation = evidence.get("navigation_outcome")
    legacy_navigation = {"status_code": 200, "content_type": "text/html", "redirect_count": 0, "outcome": "success"}
    diagnostics = {
        "admin_page_detected": False,
        "login_page_detected": False,
        "authenticated_context_detected": False,
        "challenge_page_detected": False,
        "error_page_detected": False,
        "admin_detection_signals": [],
    }
    if navigation != legacy_navigation and navigation != {**legacy_navigation, **diagnostics}:
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
    if version == EVIDENCE_SCHEMA_VERSION_DUPLICATE_H1:
        inventory_h1 = evidence.get("h1_inventory")
        if (
            evidence.get("h1_count") != 2
            or evidence.get("primary_h1") != EXPECTED_H1
            or evidence.get("body_h1") != EXPECTED_BODY_H1
            or not _valid_duplicate_h1_inventory(inventory_h1)
        ):
            return False, "Browser evidence duplicate-H1 inventory is invalid."
        primary_index = normalized_visible.find(EXPECTED_H1)
        body_index = normalized_visible.find(EXPECTED_BODY_H1)
        if primary_index < 0 or body_index <= primary_index:
            return False, "Browser evidence visible content does not preserve the locked H1 order."
    return True, "Verified."


def _valid_duplicate_h1_inventory(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 2:
        return False
    required = {"text", "ordinal", "dom_path", "classes", "ancestor_classes", "visible", "source_classification"}
    if any(not isinstance(item, dict) or set(item) != required for item in value):
        return False
    first, second = value
    if [first.get("ordinal"), second.get("ordinal")] != [1, 2]:
        return False
    if [first.get("text"), second.get("text")] != [EXPECTED_H1, EXPECTED_BODY_H1]:
        return False
    if [first.get("source_classification"), second.get("source_classification")] != ["theme_owned_post_title", "atlas_body_content"]:
        return False
    if not all(item.get("visible") is True and isinstance(item.get("dom_path"), str) and item["dom_path"] for item in value):
        return False
    if first["dom_path"] == second["dom_path"] or "wp-block-post-title" not in first.get("classes", []):
        return False
    if not ({"entry-content", "wp-block-post-content"} & set(second.get("ancestor_classes", []))):
        return False
    return all(
        isinstance(item.get("classes"), list)
        and isinstance(item.get("ancestor_classes"), list)
        and item["classes"] == sorted(set(item["classes"]))
        and item["ancestor_classes"] == sorted(set(item["ancestor_classes"]))
        for item in value
    )


def _html_result(response: httpx.Response, outcome: str, source: str) -> dict[str, Any]:
    final_url = str(response.url)
    headers = {key.lower(): value for key, value in response.headers.items()}
    body = response.text
    context = classify_public_page_context(body, final_url=final_url, status_code=response.status_code)
    base: dict[str, Any] = {"source": source, "outcome": outcome, "final_url": final_url, "status_code": response.status_code, "content_type": headers.get("content-type", ""), "cache_headers": {key: value for key, value in headers.items() if key in CACHE_HEADERS}, "verified": False, **context}
    if 300 <= response.status_code < 400 or final_url != EXPECTED_URL:
        return {**base, "outcome": "unexpected_redirect"}
    if response.status_code == 403 and BOT_PATTERN.search(body + " " + " ".join(headers.values())):
        return {**base, "outcome": "bot_protection_blocked"}
    if response.status_code in {404, 500, 502, 503, 504}:
        return {**base, "outcome": "error_page_detected"}
    if response.status_code >= 400:
        return {**base, "outcome": "unavailable"}
    if "text/html" not in headers.get("content-type", "").lower() or any(
        context[field]
        for field in ("admin_page_detected", "login_page_detected", "authenticated_context_detected", "challenge_page_detected", "error_page_detected")
    ):
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
