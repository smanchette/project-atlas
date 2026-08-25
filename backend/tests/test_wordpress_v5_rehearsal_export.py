from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import sys
from types import ModuleType
from typing import Any, Iterator

import pytest


ROOT = Path(__file__).resolve().parents[2]
BUILDER_PATH = ROOT / "wordpress" / "build_performance_local_v5_rehearsal.py"
RENDERER_PATH = (
    ROOT
    / "wordpress"
    / "project-atlas-metadata-bridge-0.57.8"
    / "includes"
    / "performance-local-v5-renderer.php"
)
SCHEMA_VERSION = "project-atlas-performance-local-v5-wordpress@1"
SPECIAL_DEMO_LABEL = "DEMO SPECIAL — NOT SITE CONTENT"
EXPECTED_TOP_LEVEL_KEYS = (
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
EXPECTED_FIXTURE_KEYS = (
    "city_service",
    "estimate",
    "special_demo",
    "optional_modules",
    "business_location",
    "valid_sixth_field",
    "invalid_extra_field",
)
EXPECTED_INPUT_IDENTITIES = {
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/03-api-generated-pages.json"
    ): "190e0d2cf458e2c5f9bc99873af9e99d05e04efa7d220252a63beb3323b1379e",
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/04-api-site-plans-1-compositions.json"
    ): "7fa5414cf7e284c5da1327f476296e772fc768466cd40304f711e55223dc252e",
    (
        ".runtime/performance-local-v5-fullsite-evidence/"
        "run-20260819-053658Z/raw-api-inputs/02-api-site-plans-1.json"
    ): "db01f91748edee10c67cc6c19a96ec4caa90014bbf3b4d87f1bce92373b14a6b",
    (
        ".runtime/performance-local-v4-layout-review/20260818-034726/"
        "full-site-v3-draft-preview-page41.json"
    ): "5e9f69db093ee488de3dd886d14e3f9fd8dec32c6924b1b5350b10915a904003",
    (
        ".runtime/performance-local-v3-rehearsal/20260815_060850/"
        "checkpoint-a-evidence.json"
    ): "69d72d8277be77164b7fd651fdbf0d2a78c646b5f0c8c271f608c41c084bf260",
}
PRODUCTION_BOUNDARY_PATHS = (
    ROOT / "backend" / "app" / "services" / "page_export.py",
    ROOT / "backend" / "app" / "services" / "theme_configurations.py",
    ROOT / "backend" / "app" / "services" / "theme_delivery.py",
    ROOT / "backend" / "app" / "services" / "form_submission_gateway.py",
    ROOT / "backend" / "app" / "services" / "wordpress_sandbox.py",
)
PRODUCTION_MODULE_NAMES = frozenset(
    {
        "app.services.page_export",
        "app.services.theme_configurations",
        "app.services.theme_delivery",
        "app.services.form_submission_gateway",
        "app.services.wordpress_sandbox",
    }
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


PRODUCTION_BOUNDARY_BEFORE_IMPORT = {
    path: (_sha256(path), path.stat().st_mtime_ns) for path in PRODUCTION_BOUNDARY_PATHS
}
MODULES_BEFORE_BUILDER_IMPORT = frozenset(sys.modules)


@pytest.fixture(scope="module")
def builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "atlas_wordpress_v5_rehearsal_builder_focused_test",
        BUILDER_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def payloads(builder: ModuleType) -> list[dict[str, Any]]:
    result = builder.build_rehearsal_payloads(ROOT)
    assert isinstance(result, list)
    return result


@pytest.fixture(scope="module")
def fixtures(payloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {payload["payload_identity"]["fixture_key"]: payload for payload in payloads}


def _load_json(relative_path: str) -> Any:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


def _component(composition: dict[str, Any], instance_key: str) -> dict[str, Any]:
    matches = [
        item["resolved_data"]
        for item in composition["effective_components"]
        if item["instance_key"] == instance_key
    ]
    assert len(matches) == 1
    return matches[0]


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def _keys(value: Any) -> Iterator[str]:
    if isinstance(value, list):
        for item in value:
            yield from _keys(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _keys(item)


def _fixture(payloads: list[dict[str, Any]], key: str) -> dict[str, Any]:
    matches = [item for item in payloads if item["payload_identity"]["fixture_key"] == key]
    assert len(matches) == 1
    return matches[0]


def test_builder_import_is_stdlib_only_and_leaves_production_boundaries_untouched(
    builder: ModuleType,
) -> None:
    assert builder.__name__ == "atlas_wordpress_v5_rehearsal_builder_focused_test"
    newly_loaded = frozenset(sys.modules) - MODULES_BEFORE_BUILDER_IMPORT
    assert newly_loaded.isdisjoint(PRODUCTION_MODULE_NAMES)
    assert {
        path: (_sha256(path), path.stat().st_mtime_ns) for path in PRODUCTION_BOUNDARY_PATHS
    } == PRODUCTION_BOUNDARY_BEFORE_IMPORT


def test_builder_verifies_all_five_frozen_sha256_inputs(builder: ModuleType) -> None:
    assert dict(builder.FROZEN_INPUTS) == EXPECTED_INPUT_IDENTITIES
    assert {
        relative_path: _sha256(ROOT / relative_path)
        for relative_path in EXPECTED_INPUT_IDENTITIES
    } == EXPECTED_INPUT_IDENTITIES


def test_frozen_identity_mismatch_fails_closed(
    builder: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    sealed = tmp_path / "sealed.json"
    sealed.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(builder, "FROZEN_INPUTS", (("sealed.json", "0" * 64),))
    with pytest.raises(builder.RehearsalExportError, match="identity mismatch"):
        builder._load_frozen_inputs(tmp_path)


def test_output_is_deterministic_and_uses_the_exact_payload_envelope(
    builder: ModuleType,
    payloads: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    assert builder.write_rehearsal_payloads(ROOT, first) == first.resolve()
    assert builder.write_rehearsal_payloads(ROOT, second) == second.resolve()
    assert first.read_bytes() == second.read_bytes() == builder.deterministic_json(payloads)
    assert json.loads(first.read_text(encoding="utf-8")) == payloads
    assert tuple(item["payload_identity"]["fixture_key"] for item in payloads) == (
        EXPECTED_FIXTURE_KEYS
    )
    for payload in payloads:
        assert tuple(payload) == EXPECTED_TOP_LEVEL_KEYS
        assert payload["schema_version"] == SCHEMA_VERSION
        assert payload["rehearsal_only"] is True


def test_page_41_city_service_payload_is_source_exact(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    pages = _load_json(next(iter(EXPECTED_INPUT_IDENTITIES)))
    compositions = _load_json(tuple(EXPECTED_INPUT_IDENTITIES)[1])
    page = next(item for item in pages if item["id"] == 41)
    composition = next(item for item in compositions if item["generated_page_id"] == 41)
    city = fixtures["city_service"]

    assert city["surface"] == "city_service"
    assert city["payload_identity"]["source_page"] == "generated-page:41"
    assert city["payload_identity"]["source_composition"] == "composition:41:v8"
    assert city["payload_identity"]["source_hash"] == composition["source_hash"]
    assert city["page"] == {
        "page_type": page["page_type"],
        "title": page["page_title"],
        "slug": page["page_slug"],
        "meta_title": page["meta_title"],
        "meta_description": page["meta_description"],
        "h1": page["h1"],
    }

    source_hero = _component(composition, "hero")
    source_hero_media = _component(composition, "media_placement:requirement-257")
    assert city["hero"]["h1"] == source_hero["title"]
    assert city["hero"]["introduction"] == source_hero["intro"]
    assert PurePosixPath(city["hero"]["media"]["src"]).name == PurePosixPath(
        source_hero_media["asset_url"]
    ).name
    assert city["hero"]["media"]["alt"] == source_hero_media["alt_text"]
    assert city["hero"]["media"]["title"] == source_hero_media["image_title"]
    assert city["hero"]["media"]["focal_x"] == source_hero_media["focal_x"]
    assert city["hero"]["media"]["focal_y"] == source_hero_media["focal_y"]

    expected_sections = (
        "service_summary:why_it_matters",
        "content_section:signs_section",
        "content_section:process_section",
        "content_section:prep_section",
        "content_section:realtor_property_manager_section",
    )
    for emitted, instance_key in zip(city["sections"][:5], expected_sections):
        source = _component(composition, instance_key)
        assert emitted["key"] == source["key"]
        assert emitted["heading"] == source["heading"]
        assert emitted["body"] == source["body"]
    final_cta = _component(composition, "final_cta")
    assert city["sections"][-1] == {
        "key": "final_conversion",
        "heading": final_cta["heading"],
        "body": final_cta["body"],
        "media": None,
    }
    assert city["faq"] == _component(composition, "faq")["items"]
    assert [item["label"] for item in city["related_pages"]] == [
        item["label"] for item in _component(composition, "destination_cards")["links"]
    ]
    assert city["footer"]["navigation"]
    assert all(
        tuple(item) == ("label", "href")
        for item in city["footer"]["navigation"]
    )
    assert all("parent_label" not in item for item in city["footer"]["navigation"])


def test_all_media_is_normalized_to_the_same_origin_upload_namespace(
    payloads: list[dict[str, Any]],
) -> None:
    media_paths = [
        value
        for payload in payloads
        for value in _strings(payload)
        if value.startswith("/wp-content/uploads/")
    ]
    assert media_paths
    assert all(path.startswith("/wp-content/uploads/atlas-v5/") for path in media_paths)
    assert all("/" not in path.removeprefix("/wp-content/uploads/atlas-v5/") for path in media_paths)


def test_conditional_surfaces_preserve_reviewed_self_link_resolution(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    city = fixtures["city_service"]
    estimate = fixtures["estimate"]
    special = fixtures["special_demo"]

    assert city["sticky_action"]["action"] == {
        "mode": "estimate",
        "label": "Request an Estimate",
        "href": "/request-an-estimate/",
    }
    assert city["hero"]["estimate_action"] == {
        "label": "Request an Estimate",
        "href": "/request-an-estimate/",
    }
    assert estimate["surface"] == "estimate"
    assert estimate["hero"] is None
    assert estimate["conditional"]["estimate"]["heading"] == "Request an Estimate"
    assert estimate["sticky_action"]["action"] == {
        "mode": "special",
        "label": SPECIAL_DEMO_LABEL,
        "href": "/special/",
    }
    assert special["surface"] == "special_demo"
    assert special["hero"] is None
    assert special["page"]["h1"] == SPECIAL_DEMO_LABEL
    assert special["conditional"]["special"]["headline"] == SPECIAL_DEMO_LABEL
    assert special["conditional"]["special"]["demo_label"] == SPECIAL_DEMO_LABEL
    assert special["sticky_action"]["action"] == {
        "mode": "estimate",
        "label": "Request an Estimate",
        "href": "/request-an-estimate/",
    }


def test_optional_modules_are_absent_by_default_and_demo_only_when_selected(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    for key in ("city_service", "estimate", "special_demo"):
        assert fixtures[key]["optional_modules"] == {
            "review_trust": None,
            "location_map": None,
        }

    optional = fixtures["optional_modules"]["optional_modules"]
    assert optional["review_trust"]["presentation"] == "local_rehearsal"
    assert len(optional["review_trust"]["sources"]) == 3
    assert {
        source["public_name"] for source in optional["review_trust"]["sources"]
    } == {"DEMO TRUST SOURCE — NOT SITE CONTENT"}
    assert all(source["profile_href"] is None for source in optional["review_trust"]["sources"])
    assert all(source["rating_text"] is None for source in optional["review_trust"]["sources"])
    assert all(
        source["review_count_text"] is None
        for source in optional["review_trust"]["sources"]
    )
    location = optional["location_map"]
    assert location["mode"] == "city_service_area"
    assert location["heading"] == "Serving Orlando, Florida"
    assert location["target_city"] == "Orlando"
    assert location["target_state"] == "Florida"
    assert location["embed_src"] is None
    assert location["demo_label"] == "DEMO MAP — NOT SITE CONTENT"
    assert location["presentation"] == "local_rehearsal"


def test_business_location_fixture_is_true_location_shaped_and_request_free(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    payload = fixtures["business_location"]
    assert payload["surface"] == "city_service"
    assert payload["optional_modules"]["review_trust"] is None
    location = payload["optional_modules"]["location_map"]
    assert tuple(location) == (
        "mode",
        "heading",
        "approved_location_name",
        "address_lines",
        "description",
        "phone_action",
        "directions_action",
        "map_title",
        "embed_src",
        "demo_label",
        "presentation",
    )
    assert location["mode"] == "business_location"
    assert location["approved_location_name"] == "DEMO BUSINESS LOCATION — NOT SITE CONTENT"
    assert location["address_lines"] == [
        "123 Demo Service Road",
        "Example City, Florida 00000",
    ]
    assert location["description"]
    assert location["phone_action"] == {
        "label": f"Call {payload['website']['phone_display']}",
        "href": payload["website"]["phone_href"],
    }
    assert location["directions_action"] == {
        "label": "Get directions",
        "href": "/demo-directions/",
    }
    assert location["embed_src"] is None
    assert location["demo_label"] == "DEMO MAP — NOT SITE CONTENT"
    assert location["presentation"] == "local_rehearsal"
    assert "target_city" not in location and "target_state" not in location


def test_form_contract_is_exactly_five_with_only_the_valid_sixth_fixture_allowed(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    default_keys = ["name", "phone", "postal-code", "requested-service", "message"]
    for key in (
        "city_service", "estimate", "special_demo", "optional_modules", "business_location",
    ):
        form = fixtures[key]["form"]
        assert form["state"] == "disabled"
        assert form["anchor"] == "estimate-form"
        assert [field["field_key"] for field in form["fields"]] == default_keys
        assert all("value" not in field and "default_value" not in field for field in form["fields"])

    sixth_fields = fixtures["valid_sixth_field"]["form"]["fields"]
    assert [field["field_key"] for field in sixth_fields] == [*default_keys, "email"]
    assert sixth_fields[-1] == {
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
    invalid_fields = fixtures["invalid_extra_field"]["form"]["fields"]
    assert len(invalid_fields) == 7
    assert invalid_fields[:6] == sixth_fields
    assert invalid_fields[-1]["field_key"] == "unexpected-extra"
    assert invalid_fields[-1]["order"] == 7


def test_payloads_contain_no_external_urls_html_secrets_or_customer_values(
    payloads: list[dict[str, Any]],
) -> None:
    forbidden_keys = {
        "api_key",
        "audit_identity",
        "csrf_policy",
        "customer_data",
        "destination_configured",
        "form_submission",
        "idempotency_strategy",
        "password",
        "provider_key",
        "provider_secret_reference",
        "request_values",
        "secret",
        "smtp",
        "submission",
        "wordpress_post_id",
        "wordpress_url",
    }
    public_contact_email = payloads[0]["website"]["contact_email"]
    for payload in payloads:
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        assert not re.search(r"https?://", serialized, flags=re.IGNORECASE)
        assert not re.search(r"<\/?[a-z][^>]*>", serialized, flags=re.IGNORECASE)
        assert all(marker not in serialized.lower() for marker in ("theme lab", "theme-lab", "theme_lab"))
        assert forbidden_keys.isdisjoint(set(_keys(payload)))
        assert payload["form"]["state"] == "disabled"
        assert "endpoint" not in payload["form"]
        emails = [
            match
            for value in _strings(payload)
            for match in re.findall(
                r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
                r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+",
                value,
            )
        ]
        assert set(emails) <= {public_contact_email}


def test_payload_resource_identities_are_generic_and_not_wordpress_bound(
    payloads: list[dict[str, Any]],
) -> None:
    for payload in payloads:
        identity = payload["payload_identity"]
        assert tuple(identity) == (
            "fixture_key",
            "source_page",
            "source_composition",
            "source_hash",
            "frozen_inputs",
        )
        assert identity["fixture_key"] in EXPECTED_FIXTURE_KEYS
        assert re.fullmatch(r"generated-page:[1-9][0-9]*", identity["source_page"])
        assert re.fullmatch(
            r"composition:[1-9][0-9]*:v[1-9][0-9]*",
            identity["source_composition"],
        )
        assert re.fullmatch(r"[0-9a-f]{64}", identity["source_hash"])
        assert re.fullmatch(r"website:[1-9][0-9]*", payload["website"]["identity"])
        assert "wordpress" not in json.dumps(identity, sort_keys=True).lower()
        assert "post" not in identity


def test_wordpress_renderer_contract_is_generic_and_not_theme_lab_or_page_bound() -> None:
    source = RENDERER_PATH.read_text(encoding="utf-8")
    lowered = source.lower()
    for forbidden_literal in (
        "page 41",
        "page41",
        "generated-page:41",
        "composition:41",
        "orlando",
        "flo-zone",
        "flo_zone",
        "flozone",
        "page 8",
        "page8",
        "theme_lab",
        "theme lab",
        "localhost",
        "siteground",
    ):
        assert forbidden_literal not in lowered
    assert not re.search(r"https?://|\bwww\.|\b[a-z0-9-]+\.(?:com|net|org)\b", lowered)
    assert "in_array(count($value['fields']), [5, 6], true)" in source
    assert "count($value['fields'])" in source
    assert "ATLAS_PERFORMANCE_LOCAL_V5_SPECIAL_MARKER" in source


def test_theme_is_v5_rehearsal_projection_of_the_frozen_effective_tokens(
    fixtures: dict[str, dict[str, Any]],
) -> None:
    compositions = _load_json(tuple(EXPECTED_INPUT_IDENTITIES)[1])
    composition = next(item for item in compositions if item["generated_page_id"] == 41)
    resolved_theme = composition["resolved_theme"]
    city_theme = fixtures["city_service"]["theme"]
    assert city_theme["family"] == "performance-local"
    assert city_theme["version"] == 5
    assert city_theme["tokens"] == resolved_theme["effective_tokens"]
    assert city_theme["source_theme"] == {
        "key": resolved_theme["source_identity"]["theme_key"],
        "version": resolved_theme["source_identity"]["theme_version"],
        "token_contract_version": resolved_theme["source_identity"][
            "token_contract_version"
        ],
        "token_hash_sha256": resolved_theme["source_identity"]["token_hash_sha256"],
    }
