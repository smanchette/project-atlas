from __future__ import annotations

import hashlib
from html import unescape
from html.parser import HTMLParser
import re
from typing import Any

from app.schemas.wordpress import (
    WordPressDraftGateResult,
    WordPressHeadingCorrectionDryRun,
)
from app.services.wordpress_sandbox import wordpress_heading_contract

ATLAS_PAGE_ID = 41
WORDPRESS_POST_ID = 8
EXPECTED_TITLE = "Drywood Termite Tenting in Orlando, FL"
EXPECTED_BODY_HEADING = "Drywood Termite Tenting in Orlando, Florida"
EXPECTED_SLUG = "drywood-termite-tenting-orlando-fl"
EXPECTED_URL = "https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/"
EXPECTED_FEATURED_MEDIA = 31
EXPECTED_CURRENT_BODY_HASH = "1144c89c046bfd74d3381560afdc5b7ec81f9a01e6de73fa929f2dc3b7ef7705"
CURRENT_HEADING_FRAGMENT = f"<h1>{EXPECTED_BODY_HEADING}</h1>"
PROPOSED_HEADING_FRAGMENT = f"<h2>{EXPECTED_BODY_HEADING}</h2>"
FORBIDDEN_REQUEST_FIELDS = {
    "title",
    "slug",
    "status",
    "excerpt",
    "featured_media",
    "template",
    "parent",
    "menu_order",
    "meta",
    "metadata",
    "media",
}


def canonicalize_wordpress_body(value: str) -> str:
    return re.sub(r">\s+<", "><", value.replace("\r\n", "\n")).strip()


def wordpress_body_hash(value: str) -> str:
    return hashlib.sha256(canonicalize_wordpress_body(value).encode("utf-8")).hexdigest()


def propose_orlando_body_correction(current_body: str) -> str:
    if not current_body.startswith(CURRENT_HEADING_FRAGMENT):
        raise ValueError("The Orlando body does not start with the locked Atlas H1 fragment.")
    return PROPOSED_HEADING_FRAGMENT + current_body[len(CURRENT_HEADING_FRAGMENT) :]


def build_orlando_heading_correction_dry_run(
    page_rest: dict[str, Any] | None,
    rendered_html: str = "",
    rendered_h1_inventory: list[dict[str, Any]] | None = None,
) -> WordPressHeadingCorrectionDryRun:
    page_available = page_rest is not None
    page_rest = page_rest or {}
    content_available = page_available and "content" in page_rest
    current_body = _resource_text(page_rest.get("content")) if content_available else ""
    current_hash = wordpress_body_hash(current_body) if content_available else None
    proposed_body = ""
    try:
        proposed_body = propose_orlando_body_correction(current_body)
    except ValueError:
        pass

    request_payload = {"content": proposed_body} if proposed_body else {}
    rendered_available = rendered_h1_inventory is not None or bool(rendered_html)
    current_headings = rendered_h1_inventory if rendered_h1_inventory is not None else _headings(rendered_html)
    if rendered_h1_inventory is not None:
        proposed_headings = [item for item in current_headings if item.get("source_classification") != "atlas_body_content"] if proposed_body else current_headings
    else:
        simulated_html = rendered_html.replace(CURRENT_HEADING_FRAGMENT, PROPOSED_HEADING_FRAGMENT, 1) if proposed_body else rendered_html
        proposed_headings = _headings(simulated_html)
    title = _resource_text(page_rest.get("title"))
    first = current_headings[0] if len(current_headings) > 0 else {}
    second = current_headings[1] if len(current_headings) > 1 else {}
    tail_unchanged = bool(
        proposed_body
        and current_body[len(CURRENT_HEADING_FRAGMENT) :]
        == proposed_body[len(PROPOSED_HEADING_FRAGMENT) :]
    )
    request_shape_valid = set(request_payload) == {"content"} and not (
        set(request_payload) & FORBIDDEN_REQUEST_FIELDS
    )

    gates = [
        _gate("target_id", "WordPress page 8 is the only target", page_rest.get("id") == WORDPRESS_POST_ID, page_available),
        _gate("status", "Page 8 remains published", page_rest.get("status") == "publish", page_available),
        _gate("title", "Page title remains exact", title == EXPECTED_TITLE, page_available),
        _gate("slug", "Page slug remains exact", page_rest.get("slug") == EXPECTED_SLUG, page_available),
        _gate("url", "Page URL remains exact", page_rest.get("link") == EXPECTED_URL, page_available),
        _gate("featured_media", "Featured media remains 31", page_rest.get("featured_media") == EXPECTED_FEATURED_MEDIA, page_available),
        _gate("body_hash", "Current canonical body hash remains locked", current_hash == EXPECTED_CURRENT_BODY_HASH, content_available),
        _gate("body_prefix", "Current body starts with the exact Atlas H1", current_body.startswith(CURRENT_HEADING_FRAGMENT), content_available),
        _gate("two_h1", "Exactly two H1 elements currently render", len(current_headings) == 2, rendered_available),
        _gate(
            "theme_h1_first",
            "The theme Post Title is the first H1",
            first.get("text") == EXPECTED_TITLE and "wp-block-post-title" in first.get("classes", []), rendered_available,
        ),
        _gate(
            "atlas_h1_second",
            "The Atlas body heading is the second H1",
            second.get("text") == EXPECTED_BODY_HEADING
            and bool({"entry-content", "wp-block-post-content"} & set(second.get("ancestor_classes", []))), rendered_available,
        ),
        _gate("tag_only_delta", "Only the first body heading tag changes", tail_unchanged),
        _gate(
            "one_h1_result",
            "The proposed rendered result contains exactly one H1",
            len(proposed_headings) == 1
            and proposed_headings[0].get("text") == EXPECTED_TITLE
            and "wp-block-post-title" in proposed_headings[0].get("classes", []), rendered_available,
        ),
        _gate(
            "wording_sections_unchanged",
            "Heading wording and every following body section remain unchanged",
            tail_unchanged
            and CURRENT_HEADING_FRAGMENT.removeprefix("<h1>").removesuffix("</h1>")
            == PROPOSED_HEADING_FRAGMENT.removeprefix("<h2>").removesuffix("</h2>"),
        ),
        _gate("content_only_request", "Future WordPress request contains only content", request_shape_valid),
    ]
    ready = all(gate.passed for gate in gates)
    return WordPressHeadingCorrectionDryRun(
        status="dry_run_ready" if ready else "blocked",
        ready=ready,
        heading_contract=wordpress_heading_contract(ATLAS_PAGE_ID),
        current_body_hash=current_hash,
        proposed_body_hash=wordpress_body_hash(proposed_body) if proposed_body else None,
        current_heading_fragment=CURRENT_HEADING_FRAGMENT,
        proposed_heading_fragment=PROPOSED_HEADING_FRAGMENT,
        request_payload=request_payload,
        gate_results=gates,
    )


def _resource_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("raw", "rendered"):
            candidate = value.get(key)
            if isinstance(candidate, str):
                return candidate
    return ""


def _gate(code: str, label: str, passed: bool, observation_available: bool = True) -> WordPressDraftGateResult:
    if not observation_available:
        dependency = "page" if code in {"target_id", "status", "title", "slug", "url", "featured_media", "body_hash", "body_prefix"} else "rendered"
        return WordPressDraftGateResult(
            code=code,
            label=label,
            passed=False,
            message=f"blocked_due_to_missing_{dependency}_observation",
        )
    return WordPressDraftGateResult(
        code=code,
        label=label,
        passed=bool(passed),
        message="Passed." if passed else f"Blocked: {label} drifted.",
    )


class _HeadingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, list[str]]] = []
        self.headings: list[dict[str, Any]] = []
        self._active: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = next((value or "" for key, value in attrs if key == "class"), "").split()
        if tag == "h1":
            self._active = {
                "text_parts": [],
                "classes": classes,
                "ancestor_classes": [item for _, values in self.stack for item in values],
            }
        self.stack.append((tag, classes))

    def handle_endtag(self, tag: str) -> None:
        if tag == "h1" and self._active is not None:
            text = " ".join("".join(self._active.pop("text_parts")).split())
            self.headings.append({**self._active, "text": unescape(text)})
            self._active = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if self._active is not None:
            self._active["text_parts"].append(data)


def _headings(value: str) -> list[dict[str, Any]]:
    parser = _HeadingParser()
    parser.feed(value)
    parser.close()
    return parser.headings
