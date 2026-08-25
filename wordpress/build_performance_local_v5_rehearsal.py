#!/usr/bin/env python3
"""Build hash-bound, local-only Performance Local V5 rehearsal payloads.

This module deliberately has no Atlas application, database, WordPress, or
network imports.  It consumes the five sealed, ignored review artifacts that
already bind Page 41 and emits normalized fixtures for the disposable local
WordPress rehearsal only.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = "project-atlas-performance-local-v5-wordpress@1"
PAGE_ID = 41
TOP_LEVEL_KEYS = (
    "schema_version",
    "surface",
    "rehearsal_only",
    "payload_identity",
    "website",
    "navigation",
    "page",
    "sticky_action",
    "hero",
    "sections",
    "related_pages",
    "faq",
    "optional_modules",
    "form",
    "conditional",
    "footer",
    "theme",
)
FIXTURE_KEYS = (
    "city_service",
    "estimate",
    "special_demo",
    "optional_modules",
    "business_location",
    "valid_sixth_field",
    "invalid_extra_field",
)
SPECIAL_DEMO_LABEL = "DEMO SPECIAL — NOT SITE CONTENT"
MAP_DEMO_LABEL = "DEMO MAP — NOT SITE CONTENT"

FROZEN_INPUTS = (
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/03-api-generated-pages.json",
        "190e0d2cf458e2c5f9bc99873af9e99d05e04efa7d220252a63beb3323b1379e",
    ),
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/04-api-site-plans-1-compositions.json",
        "7fa5414cf7e284c5da1327f476296e772fc768466cd40304f711e55223dc252e",
    ),
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/02-api-site-plans-1.json",
        "db01f91748edee10c67cc6c19a96ec4caa90014bbf3b4d87f1bce92373b14a6b",
    ),
    (
        ".runtime/performance-local-v4-layout-review/20260818-034726/"
        "full-site-v3-draft-preview-page41.json",
        "5e9f69db093ee488de3dd886d14e3f9fd8dec32c6924b1b5350b10915a904003",
    ),
    (
        ".runtime/performance-local-v3-rehearsal/20260815_060850/"
        "checkpoint-a-evidence.json",
        "69d72d8277be77164b7fd651fdbf0d2a78c646b5f0c8c271f608c41c084bf260",
    ),
)

_EXPECTED_FORM_KEYS = (
    "name",
    "phone",
    "postal-code",
    "requested-service",
    "message",
)
_CONTROL_OR_HTML = re.compile(r"[\x00-\x1f\x7f<>]")
_SAFE_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SAFE_TEL = re.compile(r"^tel:\+[1-9][0-9]{7,14}$")
_GOVERNED_US_TEL = re.compile(r"^tel:([2-9][0-9]{9})$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RehearsalExportError(ValueError):
    """Raised when a sealed source or strict rehearsal contract is invalid."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RehearsalExportError(f"{label} must be a JSON object.")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RehearsalExportError(f"{label} must be a JSON array.")
    return value


def _text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or _CONTROL_OR_HTML.search(value)
    ):
        raise RehearsalExportError(f"{label} must be exact plain text.")
    return value


def _positive_integer(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise RehearsalExportError(f"{label} must be a positive integer.")
    return value


def _exactly_one(items: list[Any], label: str) -> Any:
    if len(items) != 1:
        raise RehearsalExportError(f"Expected exactly one {label}; found {len(items)}.")
    return items[0]


def _load_frozen_inputs(project_root: Path) -> dict[str, Any]:
    project_root = project_root.resolve()
    loaded: dict[str, Any] = {}
    for relative_path, expected_sha256 in FROZEN_INPUTS:
        path = (project_root / relative_path).resolve()
        try:
            path.relative_to(project_root)
        except ValueError as exc:
            raise RehearsalExportError(
                f"Frozen input escaped the project root: {relative_path}"
            ) from exc
        if not path.is_file():
            raise RehearsalExportError(f"Frozen input is missing: {relative_path}")
        raw = path.read_bytes()
        actual_sha256 = _sha256(raw)
        if actual_sha256 != expected_sha256:
            raise RehearsalExportError(
                "Frozen input identity mismatch for "
                f"{relative_path}: expected {expected_sha256}, got {actual_sha256}."
            )
        try:
            loaded[relative_path] = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalExportError(
                f"Frozen input is not exact UTF-8 JSON: {relative_path}"
            ) from exc
    return loaded


def _component(composition: dict[str, Any], instance_key: str) -> dict[str, Any]:
    components = _array(composition.get("effective_components"), "effective_components")
    matches = [
        _object(item, f"component {instance_key}")
        for item in components
        if isinstance(item, dict) and item.get("instance_key") == instance_key
    ]
    component = _object(_exactly_one(matches, f"component {instance_key}"), instance_key)
    return _object(component.get("resolved_data"), f"{instance_key}.resolved_data")


def _component_by_key(draft: dict[str, Any], component_key: str) -> dict[str, Any]:
    components = _array(draft.get("components"), "draft components")
    matches = [
        _object(item, f"draft component {component_key}")
        for item in components
        if isinstance(item, dict) and item.get("component_key") == component_key
    ]
    return _object(_exactly_one(matches, f"draft component {component_key}"), component_key)


def _internal_href(slug: Any, label: str) -> str:
    exact_slug = _text(slug, label)
    if exact_slug == "home":
        return "/"
    if not _SAFE_SLUG.fullmatch(exact_slug):
        raise RehearsalExportError(f"Unsafe internal slug for {label}: {exact_slug}")
    return f"/{exact_slug}/"


def _phone_href(value: Any) -> str:
    destination = _text(value, "governed call destination")
    if _SAFE_TEL.fullmatch(destination):
        return destination
    governed_us = _GOVERNED_US_TEL.fullmatch(destination)
    if governed_us:
        return f"tel:+1{governed_us.group(1)}"
    raise RehearsalExportError("The governed call destination is not normalized tel data.")


def _upload_path(source_url: Any, label: str) -> str:
    source = _text(source_url, label)
    parsed = urlsplit(source)
    basename = PurePosixPath(parsed.path).name
    if (
        not basename
        or basename in {".", ".."}
        or "/" in basename
        or "\\" in basename
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", basename)
    ):
        raise RehearsalExportError(f"Unsafe media basename for {label}.")
    return f"/wp-content/uploads/atlas-v5/{basename}"


def _synthetic_upload_path(basename: str) -> str:
    return _upload_path(f"/synthetic/{basename}", "synthetic rehearsal media")


def _media(source: dict[str, Any]) -> dict[str, Any]:
    focal_x = source.get("focal_x")
    focal_y = source.get("focal_y")
    if (
        not isinstance(focal_x, (int, float))
        or isinstance(focal_x, bool)
        or not 0 <= focal_x <= 1
        or not isinstance(focal_y, (int, float))
        or isinstance(focal_y, bool)
        or not 0 <= focal_y <= 1
    ):
        raise RehearsalExportError("Media focal positions must be numbers from zero to one.")
    return {
        "src": _upload_path(source.get("asset_url"), "media asset_url"),
        "alt": _text(source.get("alt_text"), "media alt_text"),
        "title": _text(source.get("image_title"), "media image_title"),
        "focal_x": focal_x,
        "focal_y": focal_y,
    }


def _logo(source: dict[str, Any], key: str) -> dict[str, str]:
    identities = _object(source.get("identity_assets"), "identity_assets")
    asset = _object(identities.get(key), f"identity_assets.{key}")
    return {
        "src": _upload_path(asset.get("asset_url"), f"{key}.asset_url"),
        "alt": _text(
            asset.get("accessibility_description"),
            f"{key}.accessibility_description",
        ),
    }


def _navigation_items(source: dict[str, Any]) -> list[dict[str, Any]]:
    items = [_object(item, "navigation item") for item in _array(source.get("items"), "navigation items")]
    labels_by_id = {
        _positive_integer(item.get("navigation_item_id"), "navigation item id"): _text(
            item.get("label"), "navigation item label"
        )
        for item in items
    }
    normalized: list[dict[str, Any]] = []
    for item in items:
        if item.get("status") != "active":
            raise RehearsalExportError("Frozen navigation contains a non-active item.")
        parent_id = item.get("parent_navigation_item_id")
        parent_label = None
        if parent_id is not None:
            parent_label = labels_by_id.get(
                _positive_integer(parent_id, "parent navigation item id")
            )
            if parent_label is None:
                raise RehearsalExportError("Navigation parent identity is unresolved.")
        normalized.append(
            {
                "label": _text(item.get("label"), "navigation label"),
                "href": _internal_href(item.get("slug"), "navigation slug"),
                "parent_label": parent_label,
            }
        )
    return normalized


def _footer_navigation_items(source: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"label": item["label"], "href": item["href"]}
        for item in _navigation_items(source)
    ]


def _form_payload(draft: dict[str, Any]) -> dict[str, Any]:
    component = _component_by_key(draft, "compact_estimate_form")
    configuration = _object(
        component.get("configuration_payload"),
        "compact_estimate_form.configuration_payload",
    )
    if configuration.get("submission_state") != "disabled_pending_provider_configuration":
        raise RehearsalExportError("The frozen form is not provider-disabled.")
    provider = _object(configuration.get("provider"), "form provider")
    if any(
        provider.get(key) is not None
        for key in ("provider_key", "destination", "provider_secret_reference")
    ) or provider.get("test_only") is not False:
        raise RehearsalExportError("The frozen form unexpectedly contains provider configuration.")

    source_fields = [
        _object(field, "form field")
        for field in _array(configuration.get("fields"), "form fields")
    ]
    keys = tuple(field.get("field_key") for field in source_fields)
    if keys != _EXPECTED_FORM_KEYS:
        raise RehearsalExportError("The durable five-field form identity changed.")
    fields: list[dict[str, Any]] = []
    for expected_order, source in enumerate(source_fields, start=1):
        validation = _object(source.get("validation_contract"), "field validation")
        order = _positive_integer(source.get("order"), "field order")
        maximum = _positive_integer(source.get("maximum_length"), "field maximum_length")
        minimum = source.get("validation_contract", {}).get("minimum_length")
        if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 0:
            raise RehearsalExportError("Field minimum_length must be a non-negative integer.")
        if order != expected_order or validation.get("maximum_length") != maximum:
            raise RehearsalExportError("The frozen form field ordering or length contract changed.")
        required = source.get("required")
        if not isinstance(required, bool):
            raise RehearsalExportError("Form required flags must be booleans.")
        fields.append(
            {
                "field_key": _text(source.get("field_key"), "form field_key"),
                "label": _text(source.get("label"), "form label"),
                "required": required,
                "control": _text(source.get("control"), "form control"),
                "input_type": _text(source.get("input_type"), "form input_type"),
                "order": order,
                "maximum_length": maximum,
                "validation": {
                    "rule": _text(validation.get("rule"), "form validation rule"),
                    "minimum_length": minimum,
                    "maximum_length": maximum,
                },
            }
        )
    return {
        "state": "disabled",
        "anchor": "estimate-form",
        "submit_label": _text(configuration.get("submit_label"), "form submit_label"),
        "notice": _text(configuration.get("preview_notice"), "form preview_notice"),
        "fields": fields,
    }


def _sixth_field() -> dict[str, Any]:
    return {
        "field_key": "email",
        "label": "Email",
        "required": False,
        "control": "input",
        "input_type": "email",
        "order": 6,
        "maximum_length": 254,
        "validation": {
            "rule": "email_address",
            "minimum_length": 3,
            "maximum_length": 254,
        },
    }


def _invalid_extra_field() -> dict[str, Any]:
    return {
        "field_key": "unexpected-extra",
        "label": "Unexpected extra field",
        "required": False,
        "control": "input",
        "input_type": "text",
        "order": 7,
        "maximum_length": 80,
        "validation": {
            "rule": "nonempty_text",
            "minimum_length": 0,
            "maximum_length": 80,
        },
    }


def _source_context(loaded: dict[str, Any]) -> dict[str, Any]:
    pages_path = FROZEN_INPUTS[0][0]
    compositions_path = FROZEN_INPUTS[1][0]
    plan_path = FROZEN_INPUTS[2][0]
    draft_path = FROZEN_INPUTS[3][0]
    checkpoint_path = FROZEN_INPUTS[4][0]

    pages = _array(loaded.get(pages_path), "Generated Pages input")
    compositions = _array(loaded.get(compositions_path), "compositions input")
    plan = _object(loaded.get(plan_path), "Site Plan input")
    draft = _object(loaded.get(draft_path), "draft preview input")
    checkpoint = _object(loaded.get(checkpoint_path), "checkpoint input")

    page = _object(
        _exactly_one(
            [item for item in pages if isinstance(item, dict) and item.get("id") == PAGE_ID],
            f"Generated Page {PAGE_ID}",
        ),
        "Generated Page",
    )
    composition = _object(
        _exactly_one(
            [
                item
                for item in compositions
                if isinstance(item, dict) and item.get("generated_page_id") == PAGE_ID
            ],
            f"Page {PAGE_ID} composition",
        ),
        "Page composition",
    )
    planned_page = _object(
        _exactly_one(
            [
                item
                for item in _array(plan.get("planned_pages"), "planned_pages")
                if isinstance(item, dict) and item.get("generated_page_id") == PAGE_ID
            ],
            f"Page {PAGE_ID} Planned Page",
        ),
        "Planned Page",
    )

    if (
        page.get("page_type") != "city_service"
        or page.get("website_id") != composition.get("website_id")
        or plan.get("website_id") != composition.get("website_id")
        or planned_page.get("id") != composition.get("planned_page_id")
        or planned_page.get("site_plan_id") != composition.get("site_plan_id")
        or planned_page.get("website_id") != composition.get("website_id")
        or planned_page.get("page_type") != page.get("page_type")
        or planned_page.get("intended_slug") != page.get("page_slug")
        or draft.get("requested_generated_page_id") != PAGE_ID
    ):
        raise RehearsalExportError("The five frozen sources do not resolve one exact Page 41 graph.")
    if draft.get("export_eligible") is not False:
        raise RehearsalExportError("The frozen inactive draft unexpectedly became export eligible.")
    provider_state = _object(draft.get("provider_state"), "draft provider_state")
    if provider_state.get("can_submit") is not False or provider_state.get("collects_data") is not False:
        raise RehearsalExportError("The frozen inactive form is not inert.")
    checkpoint_preview = _object(
        checkpoint.get("inactive_draft_preview"),
        "checkpoint inactive_draft_preview",
    )
    checkpoint_page = _object(checkpoint_preview.get("page"), "checkpoint preview page")
    checkpoint_form = _object(
        checkpoint_preview.get("form_readiness"),
        "checkpoint form_readiness",
    )
    checkpoint_export = _object(
        checkpoint_preview.get("export_eligibility"),
        "checkpoint export_eligibility",
    )
    if (
        checkpoint_preview.get("mode") != "inactive_draft_preview"
        or checkpoint_page.get("id") != PAGE_ID
        or checkpoint_page.get("website_id") != page.get("website_id")
        or checkpoint_page.get("h1") != page.get("h1")
        or checkpoint_preview.get("governed_actions") != draft.get("governed_actions")
        or checkpoint_form.get("can_submit") is not False
        or checkpoint_form.get("submission_state")
        != "disabled_pending_provider_configuration"
        or checkpoint_export.get("eligible") is not False
    ):
        raise RehearsalExportError(
            "The sealed checkpoint no longer binds the exact inert Page 41 preview."
        )

    return {
        "page": page,
        "composition": composition,
        "planned_page": planned_page,
        "draft": draft,
    }


def _base_identity(context: dict[str, Any], fixture_key: str) -> dict[str, Any]:
    page = context["page"]
    composition = context["composition"]
    source_hash = _text(composition.get("source_hash"), "composition source_hash")
    if not _SHA256.fullmatch(source_hash):
        raise RehearsalExportError("The composition source hash is not SHA-256.")
    return {
        "fixture_key": fixture_key,
        "source_page": f"generated-page:{_positive_integer(page.get('id'), 'page id')}",
        "source_composition": (
            f"composition:{_positive_integer(composition.get('id'), 'composition id')}:"
            f"v{_positive_integer(composition.get('composition_version'), 'composition version')}"
        ),
        "source_hash": source_hash,
        "frozen_inputs": [
            {"path": relative_path, "sha256": sha256}
            for relative_path, sha256 in FROZEN_INPUTS
        ],
    }


def _target_place(context: dict[str, Any]) -> tuple[str, str]:
    planning_record = _object(context["planned_page"].get("planning_record"), "planning_record")
    answers = _object(planning_record.get("effective_answers"), "effective_answers")
    relationships = _array(answers.get("relationships"), "planning relationships")
    city_relationship = _object(
        _exactly_one(
            [item for item in relationships if isinstance(item, dict) and item.get("type") == "city"],
            "governed city relationship",
        ),
        "city relationship",
    )
    target_city = _text(city_relationship.get("name"), "target city")
    h1 = _text(context["page"].get("h1"), "page h1")
    prefix = f" in {target_city}, "
    if prefix not in h1:
        raise RehearsalExportError("The governed target City and Page H1 do not agree.")
    target_state = _text(h1.rsplit(prefix, 1)[1], "target state")
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]*", target_state):
        raise RehearsalExportError("The governed target state is not a safe place name.")
    return target_city, target_state


def _optional_modules(target_city: str, target_state: str) -> dict[str, Any]:
    sources = []
    descriptions = (
        "Structural preview for one manually approved public source.",
        "Structural preview for a second manually approved public source.",
        "Structural preview for a third manually approved public source.",
    )
    number_words = ("one", "two", "three")
    for index, (description, word) in enumerate(zip(descriptions, number_words), start=1):
        sources.append(
            {
                "source_key": f"local-rehearsal-source-{word}",
                "public_name": "DEMO TRUST SOURCE — NOT SITE CONTENT",
                "description": description,
                "badge": {
                    "src": _synthetic_upload_path(f"demo-trust-source-{index}.svg"),
                    "alt": f"Demo trust source structure {word}",
                },
                "profile_href": None,
                "rating_text": None,
                "review_count_text": None,
            }
        )
    return {
        "review_trust": {
            "heading": "Review and trust sources",
            "presentation": "local_rehearsal",
            "sources": sources,
        },
        "location_map": {
            "mode": "city_service_area",
            "heading": f"Serving {target_city}, {target_state}",
            "description": "Synthetic preview of a manually approved city service-area map.",
            "target_city": target_city,
            "target_state": target_state,
            "map_title": f"{target_city} service-area demo map — not site content",
            "embed_src": None,
            "demo_label": MAP_DEMO_LABEL,
            "presentation": "local_rehearsal",
        },
    }


def _business_location_modules(phone_display: str, phone_href: str) -> dict[str, Any]:
    return {
        "review_trust": None,
        "location_map": {
            "mode": "business_location",
            "heading": "Our Location",
            "approved_location_name": "DEMO BUSINESS LOCATION — NOT SITE CONTENT",
            "address_lines": [
                "123 Demo Service Road",
                "Example City, Florida 00000",
            ],
            "description": "Synthetic preview of a manually approved public business location.",
            "phone_action": {
                "label": f"Call {phone_display}",
                "href": phone_href,
            },
            "directions_action": {
                "label": "Get directions",
                "href": "/demo-directions/",
            },
            "map_title": "Demo business-location map — not site content",
            "embed_src": None,
            "demo_label": MAP_DEMO_LABEL,
            "presentation": "local_rehearsal",
        },
    }


def _city_payload(context: dict[str, Any]) -> dict[str, Any]:
    page = context["page"]
    composition = context["composition"]
    draft = context["draft"]

    header = _component(composition, "website_header")
    footer_source = _component(composition, "website_footer")
    utility_navigation = _component(composition, "utility_navigation")
    primary_navigation = _component(composition, "primary_navigation")
    footer_navigation = _component(composition, "footer_navigation")
    hero_source = _component(composition, "hero")
    hero_media = _component(composition, "media_placement:requirement-257")
    why_media = _component(composition, "media_placement:requirement-258")
    signs_media = _component(composition, "media_placement:requirement-256")
    related = _component(composition, "destination_cards")
    faq = _component(composition, "faq")
    final_cta = _component(composition, "final_cta")
    governed_actions = _object(draft.get("governed_actions"), "governed_actions")
    phone_href = _phone_href(governed_actions.get("call_destination"))

    page_h1 = _text(page.get("h1"), "page h1")
    if (
        hero_source.get("title") != page_h1
        or hero_source.get("page_type") != page.get("page_type")
        or hero_source.get("phone") != header.get("phone")
    ):
        raise RehearsalExportError("The Page 41 hero does not match its governed source graph.")

    _target_place(context)

    sections: list[dict[str, Any]] = []
    section_sources = (
        ("service_summary:why_it_matters", why_media),
        ("content_section:signs_section", signs_media),
        ("content_section:process_section", None),
        ("content_section:prep_section", None),
        ("content_section:realtor_property_manager_section", None),
    )
    for instance_key, media_source in section_sources:
        source = _component(composition, instance_key)
        sections.append(
            {
                "key": _text(source.get("key"), f"{instance_key} key"),
                "heading": _text(source.get("heading"), f"{instance_key} heading"),
                "body": _text(source.get("body"), f"{instance_key} body"),
                "media": _media(media_source) if media_source else None,
            }
        )
    sections.append(
        {
            "key": "final_conversion",
            "heading": _text(final_cta.get("heading"), "final CTA heading"),
            "body": _text(final_cta.get("body"), "final CTA body"),
            "media": None,
        }
    )

    related_pages = []
    for item in _array(related.get("links"), "related page links"):
        exact = _object(item, "related page")
        related_pages.append(
            {
                "label": _text(exact.get("label"), "related page label"),
                "href": _internal_href(exact.get("slug"), "related page slug"),
                "relationship_type": _text(
                    exact.get("relationship_type"), "related relationship_type"
                ),
            }
        )

    faq_items = []
    for item in _array(faq.get("items"), "FAQ items"):
        exact = _object(item, "FAQ item")
        faq_items.append(
            {
                "question": _text(exact.get("question"), "FAQ question"),
                "answer": _text(exact.get("answer"), "FAQ answer"),
            }
        )

    resolved_theme = _object(composition.get("resolved_theme"), "resolved_theme")
    source_theme = _object(resolved_theme.get("source_identity"), "theme source_identity")
    effective_tokens = _object(resolved_theme.get("effective_tokens"), "effective_tokens")
    if resolved_theme.get("fallback_used") is not False:
        raise RehearsalExportError("The frozen composition unexpectedly uses fallback Theme tokens.")

    form = _form_payload(draft)
    estimate_href = "/request-an-estimate/"
    call_label = _text(governed_actions.get("call_label"), "call label")
    estimate_label = _text(governed_actions.get("estimate_label"), "estimate label")

    payload = {
        "schema_version": SCHEMA_VERSION,
        "surface": "city_service",
        "rehearsal_only": True,
        "payload_identity": _base_identity(context, "city_service"),
        "website": {
            "identity": (
                f"website:{_positive_integer(composition.get('website_id'), 'website id')}"
            ),
            "display_name": _text(header.get("display_name"), "website display_name"),
            "company_name": _text(header.get("company_name"), "website company_name"),
            "tagline": _text(header.get("tagline"), "website tagline"),
            "phone_display": _text(header.get("phone"), "website phone"),
            "phone_href": phone_href,
            "contact_email": _text(header.get("email"), "website email"),
            "header_logo": _logo(header, "header_logo"),
            "footer_logo": _logo(footer_source, "footer_logo"),
        },
        "navigation": {
            "utility": _navigation_items(utility_navigation),
            "primary": _navigation_items(primary_navigation),
            "mobile_label": "Menu",
        },
        "page": {
            "page_type": _text(page.get("page_type"), "page type"),
            "title": _text(page.get("page_title"), "page title"),
            "slug": _text(page.get("page_slug"), "page slug"),
            "meta_title": _text(page.get("meta_title"), "page meta title"),
            "meta_description": _text(
                page.get("meta_description"), "page meta description"
            ),
            "h1": page_h1,
        },
        "sticky_action": {
            "phone": {"label": call_label, "href": phone_href},
            "action": {
                "mode": "estimate",
                "label": estimate_label,
                "href": estimate_href,
            },
        },
        "hero": {
            "eyebrow": "City Service",
            "h1": page_h1,
            "introduction": _text(hero_source.get("intro"), "hero intro"),
            "media": _media(hero_media),
            "call_action": {"label": call_label, "href": phone_href},
            "estimate_action": {"label": estimate_label, "href": estimate_href},
        },
        "sections": sections,
        "related_pages": related_pages,
        "faq": faq_items,
        "optional_modules": {"review_trust": None, "location_map": None},
        "form": form,
        "conditional": {"estimate": None, "special": None},
        "footer": {
            "navigation": _footer_navigation_items(footer_navigation),
            "company_name": _text(footer_source.get("company_name"), "footer company_name"),
            "phone_display": _text(footer_source.get("phone"), "footer phone"),
            "contact_email": _text(footer_source.get("email"), "footer email"),
            "logo": _logo(footer_source, "footer_logo"),
        },
        "theme": {
            "family": "performance-local",
            "version": 5,
            "source_theme": {
                "key": _text(source_theme.get("theme_key"), "source Theme key"),
                "version": _positive_integer(
                    source_theme.get("theme_version"), "source Theme version"
                ),
                "token_contract_version": _positive_integer(
                    source_theme.get("token_contract_version"),
                    "token contract version",
                ),
                "token_hash_sha256": _text(
                    source_theme.get("token_hash_sha256"), "Theme token hash"
                ),
            },
            "tokens": deepcopy(effective_tokens),
        },
    }
    if tuple(payload) != TOP_LEVEL_KEYS:
        raise AssertionError("Internal top-level payload key order changed.")
    return payload


def _conditional_page(
    city: dict[str, Any],
    context: dict[str, Any],
    surface: str,
) -> dict[str, Any]:
    payload = deepcopy(city)
    payload["surface"] = surface
    payload["payload_identity"] = _base_identity(context, surface)
    payload["hero"] = None
    payload["sections"] = []
    payload["related_pages"] = []
    payload["faq"] = []
    payload["optional_modules"] = {"review_trust": None, "location_map": None}
    payload["conditional"] = {"estimate": None, "special": None}
    phone = deepcopy(city["sticky_action"]["phone"])

    if surface == "estimate":
        planning_record = _object(context["planned_page"].get("planning_record"), "planning_record")
        answers = _object(planning_record.get("effective_answers"), "effective_answers")
        introduction = _text(answers.get("primary_action"), "estimate introduction")
        payload["page"] = {
            "page_type": "estimate",
            "title": "Request an Estimate",
            "slug": "request-an-estimate",
            "meta_title": f"Request an Estimate | {city['website']['display_name']}",
            "meta_description": introduction,
            "h1": "Request an Estimate",
        }
        payload["sticky_action"] = {
            "phone": phone,
            "action": {
                "mode": "special",
                "label": SPECIAL_DEMO_LABEL,
                "href": "/special/",
            },
        }
        payload["conditional"]["estimate"] = {
            "heading": "Request an Estimate",
            "introduction": introduction,
            "phone_alternative_enabled": True,
        }
    elif surface == "special_demo":
        description = (
            "No public Special is configured. This disposable local WordPress rehearsal "
            "demonstrates the optional Special-page layout only."
        )
        payload["page"] = {
            "page_type": "special_demo",
            "title": SPECIAL_DEMO_LABEL,
            "slug": "special",
            "meta_title": f"{SPECIAL_DEMO_LABEL} | {city['website']['display_name']}",
            "meta_description": description,
            "h1": SPECIAL_DEMO_LABEL,
        }
        payload["sticky_action"] = {
            "phone": phone,
            "action": {
                "mode": "estimate",
                "label": "Request an Estimate",
                "href": "/request-an-estimate/",
            },
        }
        payload["conditional"]["special"] = {
            "headline": SPECIAL_DEMO_LABEL,
            "description": description,
            "terms": None,
            "call_action_enabled": True,
            "estimate_action_enabled": True,
            "demo_label": SPECIAL_DEMO_LABEL,
        }
    else:
        raise AssertionError(f"Unsupported conditional surface: {surface}")
    return payload


def build_rehearsal_payloads(project_root: Path) -> list[dict[str, Any]]:
    """Return the seven deterministic, normalized local rehearsal fixtures."""

    loaded = _load_frozen_inputs(Path(project_root))
    context = _source_context(loaded)
    city = _city_payload(context)
    estimate = _conditional_page(city, context, "estimate")
    special = _conditional_page(city, context, "special_demo")

    optional = deepcopy(city)
    optional["payload_identity"] = _base_identity(context, "optional_modules")
    target_city, target_state = _target_place(context)
    optional["optional_modules"] = _optional_modules(target_city, target_state)

    business_location = deepcopy(city)
    business_location["payload_identity"] = _base_identity(context, "business_location")
    business_location["optional_modules"] = _business_location_modules(
        city["website"]["phone_display"],
        city["website"]["phone_href"],
    )

    valid_sixth = deepcopy(estimate)
    valid_sixth["payload_identity"] = _base_identity(context, "valid_sixth_field")
    valid_sixth["form"]["fields"].append(_sixth_field())

    invalid_extra = deepcopy(valid_sixth)
    invalid_extra["payload_identity"] = _base_identity(context, "invalid_extra_field")
    invalid_extra["form"]["fields"].append(_invalid_extra_field())

    payloads = [
        city,
        estimate,
        special,
        optional,
        business_location,
        valid_sixth,
        invalid_extra,
    ]
    identities = tuple(item["payload_identity"]["fixture_key"] for item in payloads)
    if identities != FIXTURE_KEYS:
        raise AssertionError("Internal fixture ordering changed.")
    for payload in payloads:
        if tuple(payload) != TOP_LEVEL_KEYS or payload.get("rehearsal_only") is not True:
            raise AssertionError("Internal rehearsal payload boundary changed.")
    return payloads


def deterministic_json(payloads: list[dict[str, Any]]) -> bytes:
    return (
        json.dumps(
            payloads,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def write_rehearsal_payloads(project_root: Path, output_path: Path) -> Path:
    """Build and write payloads to the exact caller-supplied local path."""

    root = Path(project_root).resolve()
    output = Path(output_path).resolve()
    frozen_paths = {(root / relative_path).resolve() for relative_path, _ in FROZEN_INPUTS}
    if output in frozen_paths:
        raise RehearsalExportError("The output path cannot overwrite a sealed frozen input.")
    if not output.parent.is_dir():
        raise RehearsalExportError("The caller-supplied output directory does not exist.")
    output.write_bytes(deterministic_json(build_rehearsal_payloads(root)))
    return output


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build sealed Performance Local V5 WordPress rehearsal payloads."
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project Atlas repository root (defaults to the parent of wordpress/).",
    )
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    arguments = _arguments()
    write_rehearsal_payloads(arguments.project_root, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
