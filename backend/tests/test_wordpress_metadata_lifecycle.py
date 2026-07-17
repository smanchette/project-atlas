from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import inspect
import json
from pathlib import Path
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import app
from app.services import wordpress_metadata_lifecycle as lifecycle
from app.services.wordpress_deployment_release import resolve_program_root


def gate_map(gates):
    return {gate.code: gate for gate in gates}


def empty_rendered():
    return {
        "atlas_metadata_marker_present": False,
        "metadata_inventory": {
            "meta_descriptions": [], "open_graph": [], "twitter": [],
            "json_ld": [], "atlas_ownership_markers": [],
        },
    }


def observation(rendered=None):
    return {"rendered": rendered or empty_rendered(), "cache_headers": {}}


EXECUTABLE_CHECKSUM = "64a20b6d6a03cef5430dd19fdc1e7eebfd6a3a0f8dcb201eaae5ee30250a3d5c"
ZIP_CHECKSUM = "09ec2903cd8367fafef97a8999d816245e8865694010929c6aa498c6abbf12b7"


def optimistic_snapshot(**changes):
    value = {
        "plugin": "project-atlas-metadata-bridge",
        "version": "0.57.5",
        "checksum": EXECUTABLE_CHECKSUM,
        "active": True,
        "rendering_enabled": False,
        "enabled_metadata_state": False,
        "activation_generation": "92888df7-5bb2-40b6-924d-f35dfd040518",
        "plugin_checksum": EXECUTABLE_CHECKSUM,
        "payload_hash": "",
        "revision": "0",
        "payload": None,
    }
    value.update(changes)
    return value


def test_routes_are_separate_post_only_surfaces():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    expected = {
        "/api/wordpress/metadata/staging/preflight/{page_id}",
        "/api/wordpress/metadata/staging/apply/{page_id}",
        "/api/wordpress/metadata/rendering/preflight/{page_id}",
        "/api/wordpress/metadata/rendering/apply/{page_id}",
        "/api/wordpress/metadata/rendering/disable/preflight/{page_id}",
        "/api/wordpress/metadata/rendering/disable/apply/{page_id}",
        "/api/wordpress/metadata/staging/rollback/preflight/{page_id}",
        "/api/wordpress/metadata/staging/rollback/apply/{page_id}",
    }
    assert {(path, "POST") for path in expected} <= routes


def test_approved_payload_is_exact_and_deterministic():
    payload = lifecycle.approved_payload().model_dump(mode="json")
    assert payload["meta_description"] == "Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida."
    assert set(payload) == {"schema_version", "page_id", "wordpress_post_id", "meta_description", "json_ld"}
    assert [node["@type"] for node in payload["json_ld"]["@graph"]] == ["Organization", "Service"]
    assert payload["json_ld"]["@graph"][0]["telephone"] == "(844) 600-8368"
    assert payload["json_ld"]["@graph"][0]["email"] == "Office@Flo-ZoneTenting.com"
    assert payload["json_ld"]["@graph"][0]["identifier"]["value"] == "JB360566"
    assert payload["json_ld"]["@graph"][1]["areaServed"] == "Orlando, Florida"
    assert lifecycle.payload_sha256() == lifecycle.payload_sha256(lifecycle.approved_payload())
    encoded = str(payload)
    for forbidden in ("LocalBusiness", "WebSite", "WebPage", "Person", "ImageObject", "BreadcrumbList", "FAQPage", "Product", "Review", "AggregateRating"):
        assert forbidden not in encoded
    assert "media" not in encoded.lower()


def test_staging_requires_empty_disabled_revision_zero():
    valid = {"payload": None, "payload_hash": "", "revision": "0", "rendering_enabled": False}
    assert all(g.passed for g in lifecycle._operation_gates("stage_metadata_payload", valid, None, [], lifecycle.payload_sha256(), observation()))
    for key, value in (("payload", {}), ("payload_hash", "a" * 64), ("revision", "1"), ("rendering_enabled", True)):
        changed = {**valid, key: value}
        assert not gate_map(lifecycle._operation_gates("stage_metadata_payload", changed, None, [], lifecycle.payload_sha256(), observation()))["initial_state"].passed


def audit(action, status="verified"):
    return type("Audit", (), {"action_type": action, "status": status})()


def staged_snapshot(enabled=False):
    return {"payload": lifecycle.approved_payload().model_dump(mode="json"), "payload_hash": lifecycle.payload_sha256(), "revision": "1", "rendering_enabled": enabled}


def test_enable_requires_verified_staging_and_does_not_accept_drift():
    gates = gate_map(lifecycle._operation_gates("enable_metadata_rendering", staged_snapshot(), object(), [audit("stage_metadata_payload")], lifecycle.payload_sha256(), observation()))
    assert gates["staged"].passed
    assert not gate_map(lifecycle._operation_gates("enable_metadata_rendering", staged_snapshot(), object(), [], lifecycle.payload_sha256(), observation()))["staged"].passed


def test_disable_preserves_payload_contract():
    gates = gate_map(lifecycle._operation_gates("disable_metadata_rendering", staged_snapshot(True), object(), [audit("enable_metadata_rendering")], lifecycle.payload_sha256(), observation()))
    assert gates["enabled"].passed
    assert lifecycle._expected_revision("disable_metadata_rendering") == "1"


def test_rollback_fails_closed_while_rendering_enabled():
    audits = [audit("stage_metadata_payload"), audit("enable_metadata_rendering"), audit("disable_metadata_rendering")]
    assert not gate_map(lifecycle._operation_gates("rollback_metadata_payload", staged_snapshot(True), object(), audits, lifecycle.payload_sha256(), observation()))["disabled"].passed
    assert all(g.passed for g in lifecycle._operation_gates("rollback_metadata_payload", staged_snapshot(False), object(), audits, lifecycle.payload_sha256(), observation()))
    assert lifecycle._expected_revision("rollback_metadata_payload") == "0"


@pytest.mark.parametrize("action", list(lifecycle.PHRASES))
def test_handle_is_short_lived_single_use_and_action_bound(action):
    lifecycle._clear_lifecycle_handles()
    request = object()
    handle = lifecycle._store_handle(action, request, "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    entry = lifecycle._consume_handle(handle, action)
    assert entry.action == action and entry.request is request
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, action)


def test_handle_rejects_wrong_action_and_restart():
    lifecycle._clear_lifecycle_handles()
    handle = lifecycle._store_handle("stage_metadata_payload", object(), "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, "enable_metadata_rendering")
    handle = lifecycle._store_handle("stage_metadata_payload", object(), "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    lifecycle._clear_lifecycle_handles()
    with pytest.raises(HTTPException): lifecycle._consume_handle(handle, "stage_metadata_payload")


def test_plugin_contract_has_four_isolated_mutations_and_disables_legacy_apply():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    assert "Version: 0.57.5" in source
    assert "atlas_legacy_combined_apply_disabled" in source
    for callback in ("atlas_metadata_stage", "atlas_metadata_rendering_enable", "atlas_metadata_rendering_disable", "atlas_metadata_stage_rollback"):
        assert f"function {callback}" in source
    stage = source[source.index("function atlas_metadata_stage("):source.index("function atlas_metadata_rendering_enable(")]
    enable = source[source.index("function atlas_metadata_rendering_enable("):source.index("function atlas_metadata_rendering_disable(")]
    disable = source[source.index("function atlas_metadata_rendering_disable("):source.index("function atlas_metadata_stage_rollback(")]
    rollback = source[source.index("function atlas_metadata_stage_rollback("):source.index("function atlas_metadata_rollback(")]
    assert "enabled'=>true" not in stage and "_atlas_metadata_enabled', '1'" not in stage
    assert "update_post_meta(8, '_atlas_metadata_payload'" not in enable
    assert "_atlas_metadata_payload'" not in disable and "_atlas_metadata_payload_hash'" not in disable
    assert "atlas_rollback_rendering_enabled" in rollback


def test_backend_and_plugin_optimistic_snapshot_fields_are_identical():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    function = source[source.index("function atlas_metadata_snapshot_hash("):source.index("function atlas_metadata_lifecycle_request(")]
    plugin_fields = tuple(re.findall(r"'([^']+)'", function[function.index("foreach ("):function.index("] as $key")]))
    assert plugin_fields == lifecycle.OPTIMISTIC_SNAPSHOT_FIELDS
    assert tuple(lifecycle._canonical_optimistic_snapshot(optimistic_snapshot())) == plugin_fields


def test_snapshot_hash_matches_plugin_canonical_json_contract():
    value = optimistic_snapshot()
    canonical = {key: value[key] for key in lifecycle.OPTIMISTIC_SNAPSHOT_FIELDS}
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    expected = hashlib.sha256(encoded).hexdigest()
    assert expected == "6d555136d773d25739b8669a49b8fdbb6712e4914b72ca87d2e070557059e4a8"
    assert lifecycle._snapshot_hash(value) == expected
    assert lifecycle._snapshot_hash(dict(reversed(list(value.items())))) == expected


def test_snapshot_hash_is_whitespace_independent_and_unicode_stable():
    payload = {"label": "Orlando – Florida", "nested": {"b": 2, "a": 1}}
    value = optimistic_snapshot(payload=payload, payload_hash="a" * 64, revision="1")
    compact = lifecycle._snapshot_hash(value)
    round_trip = json.loads(json.dumps(value, indent=4, ensure_ascii=False))
    assert lifecycle._snapshot_hash(round_trip) == compact
    encoded = json.dumps(
        lifecycle._canonical_optimistic_snapshot(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    assert "\\u2013" in encoded


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"plugin_checksum": ""}, "plugin_checksum_missing"),
        ({"plugin_checksum": "f" * 64}, "plugin_checksum_mismatch"),
        ({"plugin_checksum": ZIP_CHECKSUM}, "plugin_checksum_mismatch"),
        ({"version": "0.57.4"}, "snapshot_field_mismatch"),
        ({"active": False}, "snapshot_field_mismatch"),
        ({"rendering_enabled": 0}, "snapshot_field_mismatch"),
        ({"enabled_metadata_state": 1}, "snapshot_field_mismatch"),
        ({"revision": 0}, "snapshot_field_mismatch"),
        ({"revision": "01"}, "snapshot_field_mismatch"),
        ({"payload": ""}, "snapshot_field_mismatch"),
    ],
)
def test_snapshot_contract_fails_closed(changes, reason):
    with pytest.raises(ValueError, match=reason):
        lifecycle._snapshot_hash(optimistic_snapshot(**changes))


def test_public_status_preserves_installed_executable_checksum():
    public = lifecycle._public_status(optimistic_snapshot())
    assert public["plugin_checksum"] == EXECUTABLE_CHECKSUM
    assert public["checksum"] == EXECUTABLE_CHECKSUM
    assert lifecycle._snapshot_contract_error(public) is None


def test_missing_snapshot_field_fails_before_wordpress_request(monkeypatch):
    called = False

    class ForbiddenClient:
        def __init__(self, *args, **kwargs):
            nonlocal called
            called = True

    monkeypatch.setattr(lifecycle.httpx, "Client", ForbiddenClient)
    value = optimistic_snapshot()
    value.pop("activation_generation")
    result = lifecycle._send_operation(None, "stage_metadata_payload", object(), value)
    assert result == {"_error": "snapshot_field_mismatch", "reason_code": "snapshot_field_mismatch", "status_code": 409}
    assert called is False


@pytest.mark.parametrize(
    ("wordpress_code", "reason"),
    [
        ("atlas_snapshot_conflict", "optimistic_snapshot_hash_mismatch"),
        ("atlas_revision_conflict", "snapshot_field_mismatch"),
        ("atlas_post_changed", "snapshot_field_mismatch"),
        ("atlas_media_changed", "snapshot_field_mismatch"),
    ],
)
def test_wordpress_409_reports_only_safe_reason_codes(monkeypatch, wordpress_code, reason):
    captured = []

    class Response:
        status_code = 409

        @staticmethod
        def json():
            return {"code": wordpress_code, "message": "must not be returned"}

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, url, **kwargs):
            captured.append((url, kwargs))
            return Response()

    monkeypatch.setattr(lifecycle, "read_wordpress_settings", lambda session: SimpleNamespace(site_url="https://example.test", username="operator"))
    monkeypatch.setattr(lifecycle, "get_wordpress_application_password", lambda: "process-only")
    monkeypatch.setattr(lifecycle.httpx, "Client", Client)
    preflight = SimpleNamespace(canonical_payload=lifecycle.approved_payload(), payload_sha256=lifecycle.payload_sha256())
    result = lifecycle._send_operation(None, "stage_metadata_payload", preflight, optimistic_snapshot())
    assert result == {"_error": reason, "reason_code": reason, "wordpress_error_code": wordpress_code, "status_code": 409}
    assert len(captured) == 1 and "message" not in str(result)


def test_staging_request_uses_matching_hash_and_cannot_enable_rendering(monkeypatch):
    captured = []

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"status": "metadata_staged", "revision": "1", "rendering_enabled": False}

    class Client:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def put(self, url, **kwargs):
            captured.append((url, kwargs["json"]))
            return Response()

    monkeypatch.setattr(lifecycle, "read_wordpress_settings", lambda session: SimpleNamespace(site_url="https://example.test", username="operator"))
    monkeypatch.setattr(lifecycle, "get_wordpress_application_password", lambda: "process-only")
    monkeypatch.setattr(lifecycle.httpx, "Client", Client)
    preflight = SimpleNamespace(canonical_payload=lifecycle.approved_payload(), payload_sha256=lifecycle.payload_sha256())
    before = optimistic_snapshot()
    result = lifecycle._send_operation(None, "stage_metadata_payload", preflight, before)
    assert result == {"status": "metadata_staged", "revision": "1", "rendering_enabled": False}
    assert captured == [("https://example.test/wp-json/project-atlas/v2/pages/8/metadata/stage", {
        "expected_revision": "0",
        "expected_snapshot_hash": lifecycle._snapshot_hash(before),
        "payload": lifecycle.approved_payload().model_dump(mode="json"),
        "payload_hash": lifecycle.payload_sha256(),
    })]
    assert "rendering_enabled" not in captured[0][1]


def test_write_scope_functions_have_no_page_media_site_or_cache_mutation():
    source = inspect.getsource(lifecycle._send_operation)
    assert "PLUGIN_PATHS[action]" in source
    assert "client.put" in source
    for forbidden in ("wp/v2/pages", "wp/v2/media", "/options", "/cache", "/plugins"):
        assert forbidden not in source


def test_preflight_source_contains_no_commit_or_wordpress_write():
    source = inspect.getsource(lifecycle.lifecycle_preflight)
    assert "session.commit" not in source
    assert "client.put" not in source and "client.post" not in source
    assert "_store_handle" in source


def test_phrases_and_write_scopes_are_operation_specific():
    assert len(set(lifecycle.PHRASES.values())) == 4
    assert lifecycle.PHRASES == {
        "stage_metadata_payload": "STAGE PROJECT ATLAS METADATA PAYLOAD",
        "enable_metadata_rendering": "ENABLE PROJECT ATLAS METADATA RENDERING",
        "disable_metadata_rendering": "DISABLE PROJECT ATLAS METADATA RENDERING",
        "rollback_metadata_payload": "ROLL BACK PROJECT ATLAS METADATA PAYLOAD",
    }
    assert len(set(lifecycle.PLUGIN_PATHS.values())) == 4
