from __future__ import annotations

import hashlib
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE_0579 = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.9"
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.10"
BOOTSTRAP = SOURCE / "project-atlas-metadata-bridge.php"
RENDERER = SOURCE / "includes/performance-local-v5-renderer.php"
DELIVERY = SOURCE / "includes/performance-local-v5-form-delivery.php"
ROUTE = SOURCE / "includes/performance-local-v5-page-payload.php"
README = SOURCE / "README.md"

SEALED_0579_HASHES = {
    "README.md": "89c523814c5c40057e74146f1676a063985b49cbef5fc1f4fafa1c86753556fd",
    "assets/performance-local-v5.css": "3a227011edb8dcd56e6a30ba701dddc488c7bb1b3c5556530c49cb4b39a4445e",
    "assets/performance-local-v5.js": "82928c37ea6ef1e608b4a9232687f97d610ae95edf63e160019c1af21eff2ce4",
    "includes/performance-local-v5-form-delivery.php": "cf351cc4e9cfbef487263ba67e32edd62cb5ae9e1c58f9b88e71cf7f86aad1be",
    "includes/performance-local-v5-renderer.php": "90cd58beb60b460b277c824e220e1e7f943ee6564f45dd08bd3e8993f94f2c96",
    "project-atlas-metadata-bridge.php": "04442109ab766ea808b79afd63b4c83385e9d873996db781c5c800d3b3f93938",
    "templates/performance-local-v5-page.php": "84af149dfeea3bb8e3764e78f61533e7e018bb689c28657c5aeeb4f24854add2",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def function(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source)
    assert match, name
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, name
    return source[match.start():index]


def test_0579_source_remains_byte_exact() -> None:
    actual = {
        path.relative_to(SOURCE_0579).as_posix(): sha256(path)
        for path in SOURCE_0579.rglob("*")
        if path.is_file()
    }
    assert actual == SEALED_0579_HASHES


def test_05710_is_same_plugin_family_with_one_new_private_route_module() -> None:
    source = BOOTSTRAP.read_text(encoding="utf-8")
    assert "Plugin Name: Project Atlas Metadata Bridge" in source
    assert "Version: 0.57.10" in source
    assert "define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.10');" in source
    assert source.count("require_once") == 3
    assert "require_once __DIR__ . '/includes/performance-local-v5-renderer.php';" in source
    assert "require_once __DIR__ . '/includes/performance-local-v5-page-payload.php';" in source
    assert "require_once __DIR__ . '/includes/performance-local-v5-form-delivery.php';" in source
    assert source.index("performance-local-v5-renderer.php") < source.index("performance-local-v5-page-payload.php")
    assert source.index("performance-local-v5-page-payload.php") < source.index("performance-local-v5-form-delivery.php")
    assert {path.relative_to(SOURCE).as_posix() for path in SOURCE.rglob("*") if path.is_file()} == {
        "README.md",
        "assets/performance-local-v5.css",
        "assets/performance-local-v5.js",
        "includes/performance-local-v5-form-delivery.php",
        "includes/performance-local-v5-page-payload.php",
        "includes/performance-local-v5-renderer.php",
        "project-atlas-metadata-bridge.php",
        "templates/performance-local-v5-page.php",
    }


def test_renderer_form_template_and_assets_are_byte_exact_0579_copies() -> None:
    for relative in (
        "assets/performance-local-v5.css",
        "assets/performance-local-v5.js",
        "includes/performance-local-v5-form-delivery.php",
        "includes/performance-local-v5-renderer.php",
        "templates/performance-local-v5-page.php",
    ):
        assert (SOURCE / relative).read_bytes() == (SOURCE_0579 / relative).read_bytes(), relative


def test_route_family_methods_environment_and_capability_gates_are_exact() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    register = function(source, "atlas_performance_local_v5_page_payload_register_route")
    permission = function(source, "atlas_performance_local_v5_page_payload_permission")
    assert register.count("register_rest_route(") == 1
    assert "'project-atlas/v4'" in register
    assert "'/performance-local-v5/page-payload/(?P<post_id>\\d+)'" in register
    assert re.findall(r"'methods' => '(GET|POST|DELETE)'", register) == ["GET", "POST", "DELETE"]
    assert register.count("'permission_callback' => 'atlas_performance_local_v5_page_payload_permission'") == 3
    assert source.count("add_action('rest_api_init', 'atlas_performance_local_v5_page_payload_register_route')") == 1
    assert "atlas_performance_local_v5_environment_is_allowed()" in permission
    assert "is_user_logged_in()" in permission
    assert "current_user_can('manage_options')" in permission
    assert "current_user_can('edit_post', (int) $target->ID)" in permission
    for forbidden in (
        "HTTP_HOST",
        "SERVER_NAME",
        "wp_verify_nonce",
        "shared_secret",
        "custom_password",
        "application_passwords",
    ):
        assert forbidden not in source.lower()


def test_private_meta_get_contract_is_flat_sanitized_and_never_returns_payload() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    inspect = function(source, "atlas_performance_local_v5_page_payload_inspect")
    for key in (
        "route_schema",
        "metadata_bridge_version",
        "environment_type",
        "home",
        "siteurl",
        "blog_public",
        "post_id",
        "post_type",
        "post_status",
        "post_title",
        "post_slug",
        "metadata_exists",
        "metadata_sha256",
        "metadata_valid",
        "atlas_identity",
    ):
        assert f"'{key}' =>" in inspect
    assert "'payload' =>" not in inspect
    assert "'value' =>" not in inspect
    assert "show_in_rest" not in source
    assert "ATLAS_PERFORMANCE_LOCAL_V5_META_KEY" in source


def test_post_envelope_validator_hash_size_and_identity_contract_are_exact() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    canonicalize = function(source, "atlas_performance_local_v5_page_payload_canonicalize")
    encode = function(source, "atlas_performance_local_v5_page_payload_json")
    envelope = function(source, "atlas_performance_local_v5_page_payload_post_envelope")
    assert "array_is_list" in canonicalize
    assert "ksort($value, SORT_STRING)" in canonicalize
    for flag in (
        "JSON_UNESCAPED_SLASHES",
        "JSON_UNESCAPED_UNICODE",
        "JSON_UNESCAPED_LINE_TERMINATORS",
        "JSON_PRESERVE_ZERO_FRACTION",
    ):
        assert flag in encode
    assert "hash('sha256', $encoded)" in function(
        source, "atlas_performance_local_v5_page_payload_sha256"
    )
    assert "ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ABSOLUTE_BODY_LIMIT', 1048576" in source
    assert "ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_BODY_HEADROOM', 65536" in source
    for key in (
        "request_schema",
        "expected_prior_sha256",
        "website_id",
        "planned_page_id",
        "generated_page_id",
        "wordpress_post_id",
        "payload",
        "request_identity",
    ):
        assert f"'{key}'" in envelope
    assert "atlas_performance_local_v5_page_payload_exact_record($body, $keys)" in envelope
    assert "atlas_performance_local_v5_validate_payload($body['payload'])" in envelope
    assert "ATLAS_PERFORMANCE_LOCAL_V5_SCHEMA" in envelope
    assert "($body['payload']['rehearsal_only'] ?? null) !== true" in envelope
    assert "'website:' . $body['website_id']" in envelope
    assert "'generated-page:' . $body['generated_page_id']" in envelope
    planned = function(
        source, "atlas_performance_local_v5_page_payload_planned_page_input_matches"
    )
    assert "str_starts_with($input['path'], 'atlas/planned-page/')" in planned
    assert "^atlas/planned-page/[1-9][0-9]*$" in planned
    assert "$planned_inputs === 1" in planned
    assert "'atlas/planned-page/' . $planned_page_id" in planned
    assert "atlas_performance_local_v5_page_payload_planned_page_input_matches" in envelope
    assert "$body['planned_page_id'] !== $body['generated_page_id']" not in envelope
    assert "$body['planned_page_id'] === $body['generated_page_id']" not in envelope


def test_php_and_python_line_separator_and_float_hash_vector_is_exact() -> None:
    encoded = (
        '{"fraction":0.5,"large_exponent":1.0e+20,'
        '"line_separators":"before\u2028between\u2029after",'
        '"negative_zero":-0.0,"small_exponent":1.0e-7,'
        '"whole":16.0,"zero":0.0}'
    ).encode("utf-8")
    assert encoded == (
        b'{"fraction":0.5,"large_exponent":1.0e+20,'
        b'"line_separators":"before\xe2\x80\xa8between\xe2\x80\xa9after",'
        b'"negative_zero":-0.0,"small_exponent":1.0e-7,'
        b'"whole":16.0,"zero":0.0}'
    )
    assert hashlib.sha256(encoded).hexdigest() == (
        "b0ef0698db793640caf91ed603fdee9ab7b288cd3e71e30acc65a0988d60f276"
    )
    harness = (ROOT / "wordpress/tests/metadata-bridge-05710-page-payload.php").read_text(
        encoding="utf-8"
    )
    assert "canonical_json_matches_python_line_separator_and_float_vector" in harness
    assert "canonical_hash_cross_runtime_vector" in harness
    assert "canonical_json_rejects_non_finite_" in harness
    assert "b0ef0698db793640caf91ed603fdee9ab7b288cd3e71e30acc65a0988d60f276" in harness


def test_apply_is_one_meta_write_idempotent_cas_bound_and_verified_rollback() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    apply = function(source, "atlas_performance_local_v5_page_payload_apply")
    restore = function(source, "atlas_performance_local_v5_page_payload_restore")
    assert source.count("update_post_meta(") == 1
    assert "$prior['value']" in apply
    assert "add_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, $payload, true)" in apply
    assert "'status' => 'UNCHANGED'" in apply
    assert "'status' => 'APPLIED'" in apply
    assert "atlas_v5_page_payload_stale_prior_state" in apply
    assert apply.index("atlas_performance_local_v5_page_payload_target_matches_payload") < apply.index(
        "'status' => 'UNCHANGED'"
    )
    assert apply.index("'status' => 'UNCHANGED'") < apply.index(
        "atlas_v5_page_payload_stale_prior_state"
    )
    assert "atlas_performance_local_v5_validate_payload" in source
    assert "$readback['value'] === $payload" in apply
    assert "$readback['sha256'] === $resulting_sha256" in apply
    assert "$readback['valid']" in apply
    assert "atlas_performance_local_v5_page_payload_protected_post_state" in apply
    assert "atlas_performance_local_v5_page_payload_restore" in apply
    assert "$attempted_value" in restore
    assert "atlas_performance_local_v5_page_payload_matches_state" in restore
    assert "update_metadata(" in restore
    assert "delete_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, $attempted_value)" in restore
    assert "'outcome' => $rolled_back ? 'ROLLED_BACK' : 'ROLLBACK_FAILED'" in apply
    assert "atlas_v5_page_payload_target_identity_changed" in apply
    for forbidden in (
        "wp_update_post",
        "wp_insert_post",
        "set_post_thumbnail",
        "update_post_meta($post_id, '_wp_page_template'",
        "delete_post_meta($post_id, '_wp_page_template'",
    ):
        assert forbidden not in source


def test_delete_is_strict_expected_hash_bound_and_only_removes_v5_meta() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    remove = function(source, "atlas_performance_local_v5_page_payload_remove")
    envelope = function(source, "atlas_performance_local_v5_page_payload_delete_envelope")
    assert "project-atlas-performance-local-v5-page-payload-delete@1" in source
    for key in ("request_schema", "expected_current_sha256", "wordpress_post_id", "request_identity"):
        assert f"'{key}'" in envelope
    assert "atlas_v5_page_payload_stale_current_state" in remove
    assert "$prior['value']" in remove
    assert "'status' => 'REMOVED'" in remove
    assert "'status' => 'UNCHANGED'" in remove
    assert "'_wp_page_template'" not in remove
    assert "atlas_performance_local_v5_page_payload_restore_deleted" in remove
    assert "atlas_v5_page_payload_remove_rollback_failed" in remove


def test_target_and_private_delivery_guards_are_exact_and_sanitized() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    target = function(source, "atlas_performance_local_v5_page_payload_target_matches_payload")
    privacy = function(
        source, "atlas_performance_local_v5_page_payload_contains_private_delivery_value"
    )
    envelope = function(source, "atlas_performance_local_v5_page_payload_post_envelope")
    for field in ("post_type", "post_status", "post_title", "post_name"):
        assert f"$post->{field}" in target
    assert "'publish'" in target
    assert "$payload['page']['title']" in target
    assert "$payload['page']['slug']" in target
    assert "_project_atlas_estimate_form_delivery_v1" in privacy
    assert "'recipient_email'" in privacy
    assert "'from_email'" in privacy
    assert "atlas_performance_local_v5_page_payload_contains_private_delivery_value" in envelope
    assert "atlas_v5_page_payload_private_delivery_value" in envelope
    assert "private_values" not in envelope


def test_success_responses_have_only_sanitized_status_hashes_and_identities() -> None:
    source = ROUTE.read_text(encoding="utf-8")
    inspect = function(source, "atlas_performance_local_v5_page_payload_inspect")
    apply = function(source, "atlas_performance_local_v5_page_payload_apply")
    remove = function(source, "atlas_performance_local_v5_page_payload_remove")
    for key in (
        "route_schema",
        "metadata_bridge_version",
        "status",
        "post_id",
        "prior_sha256",
        "resulting_sha256",
        "request_identity",
    ):
        assert f"'{key}' =>" in apply or f"'{key}' =>" in remove
    assert "'payload' =>" not in apply
    assert "'payload' =>" not in remove
    response_surfaces = inspect + apply + remove
    for forbidden in ("recipient_email", "from_email", "authorization", "password", "smtp"):
        assert forbidden not in response_surfaces.lower()


def test_successor_readme_records_only_the_narrow_boundary() -> None:
    readme = README.read_text(encoding="utf-8")
    for expected in (
        "Metadata Bridge 0.57.10",
        "Application Password authentication",
        "local` or `staging",
        "one-page-at-a-time",
        "never the raw payload",
        "does not register an editor template",
        "write `_wp_page_template`",
        "does not authorize production installation",
    ):
        assert expected in readme
