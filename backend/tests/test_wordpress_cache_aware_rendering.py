from __future__ import annotations

from datetime import UTC, datetime, timedelta
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.main import app
from app.db import backup as backup_service
from app.models import WordPressCacheAwareRenderingAudit
from app.services import wordpress_cache_aware_rendering as cache
from app.services import wordpress_metadata_lifecycle as lifecycle
from app.services.wordpress_deployment_release import resolve_program_root


def gate_map(gates): return {gate.code: gate for gate in gates}


def enabled_status(**changes):
    value = {
        "plugin": cache.PLUGIN_SLUG, "version": cache.PLUGIN_VERSION, "active": True,
        "rendering_enabled": True, "enabled_metadata_state": True,
        "payload_hash": cache.payload_sha256(), "revision": "1",
        "payload": cache.approved_payload().model_dump(mode="json"),
    }
    value.update(changes); return value


def exact_preview(**changes):
    value = {
        "source": "plugin_owned_public_head_renderer", "read_only": True,
        "canonical_url": cache.CANONICAL_URL,
        "meta_descriptions": [cache.approved_payload().meta_description],
        "json_ld": [cache.approved_payload().json_ld],
        "json_ld_types": ["Organization", "Service"],
        "ownership_marker": f"Project Atlas Metadata Bridge v{cache.PLUGIN_VERSION}",
        "head_sha256": "a" * 64,
        "cache_provider": cache.CACHE_PROVIDER,
        "cache_purge_available": True,
        "cache_purge_scope": cache.CACHE_SCOPE,
        "snapshot": enabled_status(),
    }
    value.update(changes); return value


def public_html(*, duplicate=False, forbidden=False):
    description = cache.approved_payload().meta_description
    nodes = cache.approved_payload().json_ld
    if forbidden:
        nodes = {"@context": "https://schema.org", "@graph": [*nodes["@graph"], {"@type": "WebPage"}]}
    meta = f'<meta name="description" content="{description}">'
    if duplicate: meta += meta
    return f'''<html><head><title>Drywood Termite Tenting in Orlando, FL – My WordPress</title>
    <link rel="canonical" href="{cache.CANONICAL_URL}">{meta}
    <script type="application/ld+json" data-project-atlas="metadata">{json.dumps(nodes)}</script>
    </head><body><h1>Drywood Termite Tenting in Orlando, FL</h1></body></html>'''


def public_result(**changes):
    parsed = cache._parse_html(public_html())
    value = {
        "status_code": 200, "final_url": cache.CANONICAL_URL,
        "cache_headers": {"x-cache-enabled": "True", "x-proxy-cache": "MISS", "age": "0"},
        "parsed": parsed, "head_hash": parsed["head_hash"], "visible_hash": parsed["visible_hash"],
        "media32_reference_present": False,
    }
    value.update(changes); return value


def test_routes_are_separate_post_only_surfaces():
    routes = {(route.path, method) for route in app.routes for method in getattr(route, "methods", set())}
    expected = {
        "/api/wordpress/metadata/rendering/cache-aware/preflight/{page_id}",
        "/api/wordpress/metadata/rendering/cache-aware/apply/{page_id}",
        "/api/wordpress/cache/siteground/preflight/{page_id}",
        "/api/wordpress/cache/siteground/apply/{page_id}",
    }
    assert {(path, "POST") for path in expected} <= routes


def test_reason_code_contract_is_complete():
    assert cache.REASON_CODES == {
        "origin_metadata_verified", "origin_metadata_missing", "public_cache_hit_stale",
        "cache_bypass_unproven", "cache_provider_unavailable", "cache_purge_scope_unsupported",
        "cache_purge_ready", "cache_purge_failed", "public_metadata_verified",
        "public_metadata_still_stale", "public_metadata_mismatch",
        "unapproved_schema_node_present", "duplicate_metadata_present",
    }
    assert cache.CACHE_OBSERVATION_REASON_CODES == {
        "siteground_cache_provider_verified", "cache_headers_missing",
        "cache_provider_unrecognized", "cache_header_value_invalid",
        "cache_status_hit", "cache_status_miss", "cache_status_bypass",
        "stale_public_cache_confirmed",
    }


def test_cache_aware_audit_is_in_versioned_data_backup():
    assert backup_service.BACKUP_VERSION == "0.37"
    assert backup_service.BACKUP_MODELS["wordpress_cache_aware_rendering_audits"] is WordPressCacheAwareRenderingAudit


def test_plugin_artifact_is_portable_byte_equal_and_checksum_locked():
    result = cache._artifact_identity()
    assert result == {
        "valid": True, "version": "0.57.6", "zip_sha256": cache.PLUGIN_ZIP_SHA256,
        "zip_name": cache.PLUGIN_ZIP_NAME, "byte_equal": True, "portable": True, "error": None,
    }


def test_authoritative_preview_uses_same_renderer_and_is_read_only():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge-0.57.6/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    assert "function atlas_metadata_head_markup(): string" in source
    assert "echo atlas_metadata_head_markup();" in source
    preview = source[source.index("function atlas_metadata_rendering_preview"):source.index("function atlas_metadata_siteground_cache_purge")]
    assert "atlas_metadata_head_markup()" in preview
    assert "'read_only' => true" in preview
    assert not any(term in preview for term in ("update_post_meta", "delete_post_meta", "update_option", "wp_update_post"))


def test_siteground_purge_is_fixed_to_one_canonical_url():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge-0.57.6/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    purge = source[source.index("function atlas_metadata_siteground_cache_purge"):source.index("function atlas_metadata_apply")]
    assert "sg_cachepress_purge_cache(ATLAS_METADATA_CANONICAL_URL)" in purge
    assert "'scope' => 'single_canonical_url'" in purge
    assert "'cache_write_count' => 1" in purge
    assert "get_param" not in purge and "get_json_params" not in purge
    for forbidden in ("update_post_meta", "delete_post_meta", "update_option", "wp_update_post", "activate_plugin", "delete_plugins"):
        assert forbidden not in purge


@pytest.mark.parametrize("field,value", [
    ("meta_descriptions", []), ("json_ld_types", ["Organization"]),
    ("canonical_url", "https://example.com/"), ("source", "authenticated_html"),
    ("read_only", False),
])
def test_origin_verification_fails_closed(field, value):
    preview = exact_preview(**{field: value})
    gates = gate_map(cache._origin_gates({}, enabled_status(), preview))
    assert not gates["origin_metadata_verified"].passed


def test_origin_verification_accepts_exact_plugin_preview():
    assert all(g.passed for g in cache._origin_gates({}, enabled_status(), exact_preview()))


@pytest.mark.parametrize("types", [
    ["LocalBusiness"], ["Organization", "Service", "WebPage"],
    ["Organization", "Service", "FAQPage"], ["Service", "Organization"],
])
def test_origin_rejects_unapproved_or_reordered_schema(types):
    assert not cache._origin_exact(exact_preview(json_ld_types=types))


def test_public_exact_accepts_approved_metadata():
    assert cache._public_exact(public_result()) == (True, "public_metadata_verified")


def test_public_exact_rejects_duplicate_description():
    parsed = cache._parse_html(public_html(duplicate=True))
    assert cache._public_exact(public_result(parsed=parsed))[1] == "duplicate_metadata_present"


def test_public_exact_rejects_forbidden_schema_node():
    parsed = cache._parse_html(public_html(forbidden=True))
    assert cache._public_exact(public_result(parsed=parsed))[1] == "unapproved_schema_node_present"


@pytest.mark.parametrize("changes", [
    {"status_code": 404}, {"status_code": 500}, {"final_url": "https://example.com/"},
    {"media32_reference_present": True},
])
def test_public_exact_rejects_http_url_and_media_drift(changes):
    assert cache._public_exact(public_result(**changes))[0] is False


def test_cache_refresh_requires_proven_miss_age_reset_or_identity_change():
    before = {"x-proxy-cache": "HIT", "age": "900", "etag": "old"}
    assert cache._cache_refreshed(before, {"x-proxy-cache": "MISS", "age": "0"})
    assert cache._cache_refreshed(before, {"x-proxy-cache": "HIT", "age": "1"})
    assert cache._cache_refreshed(before, {"x-proxy-cache": "HIT", "age": "900", "etag": "new"})
    assert not cache._cache_refreshed(before, {"x-proxy-cache": "HIT", "age": "900", "etag": "old"})


def test_cache_provider_requires_siteground_headers():
    assert cache._siteground_cache_present({"x-cache-enabled": "True", "x-proxy-cache": "HIT"})
    assert cache._siteground_cache_hit({"x-cache-enabled": "True", "x-proxy-cache": "HIT"})
    assert not cache._siteground_cache_hit({"x-cache-enabled": "True", "x-proxy-cache": "MISS"})
    assert not cache._siteground_cache_present({"cf-cache-status": "HIT"})


@pytest.mark.parametrize("identifier", [
    "project-atlas-metadata-bridge/project-atlas-metadata-bridge",
    "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
    "project-atlas-metadata-bridge\\project-atlas-metadata-bridge",
])
def test_cache_aware_plugin_identity_reuses_fail_closed_normalization(identifier):
    plugins = [{"plugin": identifier, "version": "0.57.6", "status": "active"}]
    raw_hash = cache._hash(plugins)
    status = {"plugin": cache.PLUGIN_SLUG, "version": "0.57.6", "active": True}
    assert cache._plugin_exact({"plugins": plugins}, status)
    assert cache._hash(plugins) == raw_hash
    assert plugins[0]["plugin"] == identifier


@pytest.mark.parametrize("identifiers", [
    [
        "project-atlas-metadata-bridge/project-atlas-metadata-bridge",
        "project-atlas-metadata-bridge/project-atlas-metadata-bridge.php",
    ],
    ["../project-atlas-metadata-bridge/project-atlas-metadata-bridge"],
    ["/project-atlas-metadata-bridge/project-atlas-metadata-bridge"],
    ["project-atlas-metadata-bridge//project-atlas-metadata-bridge"],
    ["project-atlas-metadata-bridge/project-atlas-metadata-bridge\x00"],
])
def test_cache_aware_plugin_identity_rejects_duplicate_ambiguous_or_malformed(identifiers):
    plugins = [{"plugin": value, "version": "0.57.6", "status": "active"} for value in identifiers]
    status = {"plugin": cache.PLUGIN_SLUG, "version": "0.57.6", "active": True}
    assert not cache._plugin_exact({"plugins": plugins}, status)


def test_cache_aware_plugin_identity_rejects_version_or_activity_drift():
    plugin = {"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": "0.57.5", "status": "active"}
    status = {"plugin": cache.PLUGIN_SLUG, "version": "0.57.6", "active": True}
    assert not cache._plugin_exact({"plugins": [plugin]}, status)
    plugin["version"] = "0.57.6"
    plugin["status"] = "inactive"
    assert not cache._plugin_exact({"plugins": [plugin]}, status)


@pytest.mark.parametrize(("headers", "verified", "reason", "status_reason"), [
    ({"X-Cache-Enabled": "True"}, True, "siteground_cache_provider_verified", None),
    ({"x-proxy-cache": "HIT"}, True, "siteground_cache_provider_verified", "cache_status_hit"),
    ({"X-Proxy-Cache": "miss"}, True, "siteground_cache_provider_verified", "cache_status_miss"),
    ({"x-proxy-cache": "BYPASS"}, True, "siteground_cache_provider_verified", "cache_status_bypass"),
    ({"X-Proxy-Cache-Info": "DT:1"}, True, "siteground_cache_provider_verified", None),
    ({}, False, "cache_headers_missing", None),
    ({"Server": "nginx"}, False, "cache_provider_unrecognized", None),
    ({"X-Proxy-Cache": "UNKNOWN"}, False, "cache_header_value_invalid", None),
    ({"X-Cache-Enabled": "maybe"}, False, "cache_header_value_invalid", None),
])
def test_siteground_cache_provider_detection_is_precise(headers, verified, reason, status_reason):
    result = cache._siteground_cache_evidence(headers)
    assert result["verified"] is verified
    assert result["reason_code"] == reason
    assert result["status_reason_code"] == status_reason


def test_public_header_sanitizer_is_case_insensitive_and_drops_sensitive_values():
    headers = [
        ("X-Proxy-Cache", "HIT"),
        ("x-proxy-cache-info", "DT:1"),
        ("Server", "nginx"),
        ("Set-Cookie", "wordpress_logged_in=secret"),
        ("Authorization", "Basic secret"),
        ("Cookie", "session=secret"),
        ("X-Private-Token", "secret"),
    ]
    assert cache._cache_headers(headers) == {
        "server": "nginx",
        "x-proxy-cache": "HIT",
        "x-proxy-cache-info": "DT:1",
    }


def test_cache_headers_cannot_be_supplied_by_the_preflight_caller():
    request_model = cache.WordPressCacheAwareRenderingPreflightRequest
    assert "cache_headers" not in request_model.model_fields
    assert request_model.model_config.get("extra") == "forbid"


def test_public_observation_binds_direct_http_headers_to_signed_browser_identity():
    evidence = SimpleNamespace(
        rendered_head_hash="a" * 64,
        visible_content_hash="b" * 64,
        captured_at=(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        expires_at=(datetime.now(UTC) + timedelta(minutes=1)).isoformat(),
        page_identity={
            "document_title": "Drywood Termite Tenting in Orlando, FL – My WordPress",
            "h1": cache.EXPECTED_H1,
            "canonical_url": cache.CANONICAL_URL,
            "featured_image_url": "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png",
            "featured_image_alt": "Two-story Orlando Florida home professionally covered for drywood termite tenting",
        },
    )
    observation = {
        "source": "public", "outcome": "public_html_verified", "verified": True,
        "status_code": 200, "final_url": cache.CANONICAL_URL, "redirect_count": 0,
        "observed_at": datetime.now(UTC).isoformat(),
        "head_hash": "a" * 64, "visible_hash": "b" * 64,
        "document_title": [evidence.page_identity["document_title"]],
        "h1": [evidence.page_identity["h1"]], "canonical": [cache.CANONICAL_URL],
        "featured_image_url": evidence.page_identity["featured_image_url"],
        "featured_image_alt": evidence.page_identity["featured_image_alt"],
        "cache_headers": {"x-cache-enabled": "True", "x-proxy-cache": "HIT"},
        "admin_page_detected": False, "login_page_detected": False,
        "authenticated_context_detected": False, "challenge_page_detected": False,
        "error_page_detected": False,
    }
    assert cache._public_observation_matches_evidence(observation, evidence) == (True, "public_header_observation_bound")
    for changes, reason in [
        ({"status_code": 202}, "public_http_202_challenge"),
        ({"status_code": 403}, "public_http_403_error"),
        ({"final_url": "https://example.com/"}, "public_final_url_mismatch"),
        ({"redirect_count": 1}, "public_redirect_mismatch"),
        ({"observed_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat()}, "public_observation_timestamp_mismatch"),
        ({"head_hash": "c" * 64}, "public_body_identity_mismatch"),
        ({"challenge_page_detected": True}, "public_body_identity_mismatch"),
    ]:
        candidate = {**observation, **changes}
        assert cache._public_observation_matches_evidence(candidate, evidence) == (False, reason)


def test_cache_aware_preflight_reaches_ready_with_normalized_plugin_and_bound_cache_headers(monkeypatch):
    identity = {
        "document_title": "Drywood Termite Tenting in Orlando, FL – My WordPress",
        "h1": cache.EXPECTED_H1,
        "canonical_url": cache.CANONICAL_URL,
        "featured_image_url": "https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png",
        "featured_image_alt": "Two-story Orlando Florida home professionally covered for drywood termite tenting",
    }
    manual = SimpleNamespace(
        evidence_id="fresh-cache-evidence",
        evidence_schema="project-atlas-manual-browser-evidence",
        evidence_schema_version=1,
        capture_helper_version="0.59.15",
        captured_at=(datetime.now(UTC) - timedelta(seconds=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        expires_at=(datetime.now(UTC) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        rendered_head_hash="a" * 64,
        visible_content_hash="b" * 64,
        page_identity=identity,
    )
    public = {
        "source": "public", "outcome": "public_html_verified", "verified": True,
        "status_code": 200, "final_url": cache.CANONICAL_URL, "redirect_count": 0,
        "observed_at": datetime.now(UTC).isoformat(),
        "head_hash": manual.rendered_head_hash, "visible_hash": manual.visible_content_hash,
        "document_title": [identity["document_title"]], "h1": [identity["h1"]],
        "canonical": [identity["canonical_url"]],
        "featured_image_url": identity["featured_image_url"], "featured_image_alt": identity["featured_image_alt"],
        "cache_headers": {"x-cache-enabled": "True", "x-proxy-cache": "HIT", "x-proxy-cache-info": "DT:1"},
        "admin_page_detected": False, "login_page_detected": False,
        "authenticated_context_detected": False, "challenge_page_detected": False, "error_page_detected": False,
    }
    empty_inventory = {
        "meta_descriptions": [], "canonicals": [cache.CANONICAL_URL], "open_graph": [], "twitter": [],
        "json_ld": [], "title_count": 1, "canonical_count": 1, "atlas_ownership_markers": [],
        "featured_image_references": [], "media32_references": [], "unexpected_metadata_owners": [], "duplicates": [],
    }
    observed = {
        "plugins": [{"plugin": "project-atlas-metadata-bridge/project-atlas-metadata-bridge", "version": "0.57.6", "status": "active"}],
        "page": {"id": 8, "status": "publish", "featured_media": 31},
        "page_snapshot_hash": "1" * 64, "page_body_hash": cache.EXPECTED_CORRECTED_BODY_HASH,
        "media31_snapshot_hash": "3" * 64, "media32_snapshot_hash": "4" * 64,
        "page_references_media32": False, "site": {"name": "My WordPress", "description": ""},
        "rendered": {
            "h1": [cache.EXPECTED_H1], "canonical": [cache.CANONICAL_URL],
            "metadata_inventory": empty_inventory, "atlas_metadata_marker_present": False,
            "media32_reference_present": False, "public_http_observation": public,
        },
        "wordpress_request_methods": ["GET"],
    }
    disabled = {
        "plugin": cache.PLUGIN_SLUG, "version": "0.57.6", "active": True,
        "rendering_enabled": False, "enabled_metadata_state": False,
        "payload_hash": cache.payload_sha256(), "revision": "1",
        "payload": cache.approved_payload().model_dump(mode="json"),
    }
    staging = SimpleNamespace(id=2, action_type="stage_metadata_payload", status="verified")
    recovery = SimpleNamespace(id=4, action_type="disable_metadata_rendering", status="verified", completion_mode="recovery_after_failed_enable_verification")
    state = SimpleNamespace(status="staged", payload_hash=cache.payload_sha256(), wordpress_revision="1")

    class Results:
        def __init__(self, first_value=None): self.first_value = first_value
        def first(self): return self.first_value
        def __iter__(self): return iter(())

    class Session:
        calls = 0
        def get(self, model, identifier): return staging if identifier == 2 else recovery
        def exec(self, statement):
            self.calls += 1
            return Results(state if self.calls == 1 else None)

    expected_identity = SimpleNamespace(atlas_commit="d" * 40, atlas_tag="v0.59.74")

    class Request:
        manual_browser_evidence = manual
        staging_audit_id = 2
        recovery_disable_audit_id = 4
        expected_runtime_identity = expected_identity
        repository_head = "d" * 40
        repository_origin_main = "d" * 40
        repository_tag = "v0.59.74"
        repository_working_tree_clean = True
        protected_paths_unchanged = True
        no_relevant_wordpress_change_after_backup = True
        expected_body_hash = cache.EXPECTED_CORRECTED_BODY_HASH
        expected_page_snapshot_hash = "1" * 64
        expected_media31_snapshot_hash = "3" * 64
        expected_media32_snapshot_hash = "4" * 64
        def model_dump(self, **kwargs): return {"request": "locked"}

    monkeypatch.setattr(cache, "validate_manual_browser_evidence", lambda *args, **kwargs: (True, "Verified."))
    monkeypatch.setattr(cache, "_backup_proof", lambda request: SimpleNamespace(wordpress_backup_completed_at=datetime.now(UTC) - timedelta(minutes=10)))
    monkeypatch.setattr(cache, "_backup_gates", lambda proof: [cache._gate("backups", "Backups valid", True, "")])
    monkeypatch.setattr(cache, "_observe", lambda session, proof: observed)
    monkeypatch.setattr(cache, "_read_plugin_status", lambda session: {**disabled, "snapshot": disabled})
    monkeypatch.setattr(cache, "_artifact_identity", lambda: {"valid": True})
    monkeypatch.setattr(cache, "_runtime_identity", lambda: {"verified": True})
    monkeypatch.setattr(cache, "_runtime_matches", lambda value, request: True)
    monkeypatch.setattr(cache, "_audit_three_preserved", lambda session: True)
    result = cache.rendering_preflight(Session(), 41, Request(), issue_handle=False)
    assert result.preflight_ready is True
    assert result.status == "cache_aware_rendering_preflight_ready"
    assert all(gate.passed for gate in result.gate_results)
    assert result.wordpress_write_count == result.cache_write_count == result.atlas_write_count == 0
    assert result.audit_created is False
    assert result.inspected_state["cache_evidence"]["status_reason_code"] == "cache_status_hit"


def test_rendering_handle_is_single_use_and_restart_invalidates():
    cache._clear_cache_aware_handles()
    request = SimpleNamespace(model_copy=lambda **_: request)
    handle = cache._store_rendering(request, "a" * 64, datetime.now(UTC) + timedelta(minutes=1))
    assert cache._consume_rendering(handle).binding_hash == "a" * 64
    with pytest.raises(HTTPException): cache._consume_rendering(handle)
    other = cache._store_rendering(request, "b" * 64, datetime.now(UTC) + timedelta(minutes=1))
    cache._clear_cache_aware_handles()
    with pytest.raises(HTTPException): cache._consume_rendering(other)


def test_cache_handle_is_separate_single_use_and_expires():
    cache._clear_cache_aware_handles()
    handle = cache._store_cache(7, "c" * 64, datetime.now(UTC) + timedelta(minutes=1))
    assert cache._consume_cache(handle).audit_id == 7
    with pytest.raises(HTTPException): cache._consume_cache(handle)
    expired = cache._store_cache(8, "d" * 64, datetime.now(UTC) - timedelta(seconds=1))
    with pytest.raises(HTTPException): cache._consume_cache(expired)


def test_rendering_write_uses_one_fixed_put_and_no_cache_purge(monkeypatch):
    calls = []
    monkeypatch.setattr(cache, "_authenticated_json", lambda session, method, path, body=None: calls.append((method, path, body)) or {"status": "metadata_rendering_enabled"})
    before = {"rendering_enabled": False, "enabled_metadata_state": False, "activation_generation": "g", "plugin_checksum": "a" * 64, "payload_hash": cache.payload_sha256(), "revision": "1", "payload": cache.approved_payload().model_dump(mode="json")}
    cache._send_rendering_enable(None, before)
    assert len(calls) == 1 and calls[0][0:2] == ("PUT", cache.RENDERING_PATH)
    assert set(calls[0][2]) == {"expected_revision", "expected_snapshot_hash", "payload_hash"}
    assert "cache" not in calls[0][1]


def test_cache_write_uses_one_fixed_post_and_rejects_wider_scope(monkeypatch):
    calls = []
    monkeypatch.setattr(cache, "_authenticated_json", lambda session, method, path, body=None: calls.append((method, path, body)) or {"cache_write_count": 1, "scope": cache.CACHE_SCOPE, "canonical_url": cache.CANONICAL_URL})
    assert "_error" not in cache._send_cache_purge(None)
    assert calls == [("POST", cache.CACHE_PATH, {})]
    monkeypatch.setattr(cache, "_authenticated_json", lambda *args, **kwargs: {"cache_write_count": 1, "scope": "site_wide", "canonical_url": cache.CANONICAL_URL})
    assert cache._send_cache_purge(None)["reason_code"] == "cache_purge_scope_unsupported"


def test_preflights_are_source_level_zero_write():
    for function in (cache.rendering_preflight, cache.cache_preflight):
        source = inspect.getsource(function)
        assert "_authenticated_json(session, \"PUT\"" not in source
        assert "_authenticated_json(session, \"POST\"" not in source
        assert "session.commit" not in source


def test_no_page_media_site_plugin_or_payload_mutation_transport():
    source = inspect.getsource(cache)
    for forbidden in ("/wp-json/wp/v2/pages/", "/wp-json/wp/v2/media/", "/wp-json/wp/v2/settings", "/wp-json/wp/v2/plugins/"):
        assert forbidden not in source
    assert inspect.getsource(cache.cache_apply).count("_send_cache_purge(session)") == 1
    assert inspect.getsource(cache.rendering_apply).count("_send_rendering_enable(session, before)") == 1


def test_audit_status_and_phrase_contracts_are_exact():
    assert cache.RENDERING_PHRASE == "ENABLE PROJECT ATLAS METADATA RENDERING"
    assert cache.CACHE_PHRASE == "PURGE SITEGROUND CACHE FOR PROJECT ATLAS PAGE 8"
    migration = (resolve_program_root() / "backend/alembic/versions/20260717_0022_cache_aware_rendering_audits.py").read_text(encoding="utf-8")
    for status in ("pending_rendering", "origin_verified", "pending_cache_purge", "verified", "verification_failed", "failed"):
        assert status in migration


def test_plugin_php_syntax_contract_and_routes():
    source = (resolve_program_root() / "wordpress/project-atlas-metadata-bridge-0.57.6/project-atlas-metadata-bridge.php").read_text(encoding="utf-8")
    assert "Version: 0.57.6" in source
    assert "'/pages/8/metadata/rendering/preview'" in source
    assert "'/pages/8/cache/siteground/purge'" in source
    assert "atlas_metadata_permission" in source


def test_apply_failure_recommendations_are_explicit():
    source = inspect.getsource(cache.rendering_apply)
    assert '"disable_rendering"' in source
    source = inspect.getsource(cache.cache_apply)
    assert '"retry_cache_purge"' in source and '"disable_rendering"' in source


def test_failed_cache_aware_verification_is_eligible_for_guarded_disablement():
    snapshots = {"page_snapshot_hash": "page", "page_body_hash": "body", "media31_snapshot_hash": "m31", "media32_snapshot_hash": "m32"}
    cache_audit = SimpleNamespace(
        id=1, status="verification_failed",
        transition_history=["pending_rendering", "origin_verified", "pending_cache_purge", "verification_failed"],
        wordpress_write_count=1,
        wordpress_write_scope=[f"PUT {lifecycle.PLUGIN_PATHS['enable_metadata_rendering']}"],
        recovery_recommendation="disable_rendering",
        final_state={"rendering_enabled": True, "payload_hash": lifecycle.payload_sha256(), "revision": "1"},
        page_media_snapshots={**snapshots, "site": {"name": "My WordPress", "description": ""}},
    )
    lifecycle_audits = [
        SimpleNamespace(id=2, action_type="stage_metadata_payload", status="verified"),
        SimpleNamespace(id=3, action_type="enable_metadata_rendering", status="verification_failed"),
        SimpleNamespace(id=4, action_type="disable_metadata_rendering", status="verified"),
    ]
    snapshot = enabled_status()
    state = SimpleNamespace(status="staged", payload=lifecycle.approved_payload().model_dump(mode="json"), payload_hash=lifecycle.payload_sha256(), wordpress_revision="1")
    observed = {**snapshots, "site": {"name": "My WordPress", "description": ""}, "rendered": {"atlas_metadata_marker_present": False, "metadata_inventory": {"meta_descriptions": [], "open_graph": [], "twitter": [], "json_ld": [], "atlas_ownership_markers": []}}}
    result = lifecycle._disable_eligibility(snapshot, state, lifecycle_audits, lifecycle.payload_sha256(), observed, (), [cache_audit])
    assert result["eligible"] is True
    assert result["reason_code"] == "cache_aware_recovery_disable_ready"


@pytest.mark.parametrize("change", [
    {"wordpress_write_count": 2}, {"recovery_recommendation": "retry_cache_purge"},
    {"transition_history": ["pending_rendering", "verified"]},
    {"wordpress_write_scope": ["PUT caller-controlled"]},
])
def test_cache_aware_recovery_disablement_fails_closed(change):
    candidate = {
        "id": 5, "status": "verification_failed",
        "transition_history": ["pending_rendering", "verification_failed"],
        "wordpress_write_count": 1,
        "wordpress_write_scope": [f"PUT {lifecycle.PLUGIN_PATHS['enable_metadata_rendering']}"],
        "recovery_recommendation": "disable_rendering",
        "final_state": {"rendering_enabled": True, "payload_hash": lifecycle.payload_sha256(), "revision": "1"},
        "page_media_snapshots": {"page_snapshot_hash": "p", "page_body_hash": "b", "media31_snapshot_hash": "31", "media32_snapshot_hash": "32"},
    }
    candidate.update(change)
    state = SimpleNamespace(status="staged", payload=lifecycle.approved_payload().model_dump(mode="json"), payload_hash=lifecycle.payload_sha256(), wordpress_revision="1")
    observed = {"page_snapshot_hash": "p", "page_body_hash": "b", "media31_snapshot_hash": "31", "media32_snapshot_hash": "32"}
    result = lifecycle._disable_eligibility(enabled_status(), state, [SimpleNamespace(action_type="stage_metadata_payload", status="verified")], lifecycle.payload_sha256(), observed, (), [SimpleNamespace(**candidate)])
    assert result["eligible"] is False
    assert result["reason_code"] == "cache_aware_enable_outcome_uncertain"
