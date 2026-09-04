from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.15"
DELIVERY = SOURCE / "includes/performance-local-v5-form-delivery.php"
PAGE_PAYLOAD = SOURCE / "includes/performance-local-v5-page-payload.php"
RENDERER = SOURCE / "includes/performance-local-v5-renderer.php"
SCRIPT = SOURCE / "assets/performance-local-v5.js"


def _function(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source)
    assert match, name
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, name
    return source[match.start():index]


def test_05715_private_admin_surface_is_capability_nonce_post_and_allowlist_bound() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    register = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_register_page"
    )
    handler = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_handle_post"
    )
    authorization = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_request_is_authorized",
    )
    render = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_render_page"
    )
    allowlist = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_allowed_keys"
    )
    assert "add_options_page(" in register
    assert "'manage_options'" in register
    assert "atlas_performance_local_v5_environment_is_allowed()" in register
    assert "admin_post_' . ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION" in source
    assert "admin_post_nopriv" not in source
    assert "admin_request_is_authorized($input)" in handler
    assert "($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'" in authorization
    assert "current_user_can('manage_options')" in authorization
    assert "wp_verify_nonce(" in authorization
    assert "admin_allowed_keys($command)" in authorization
    assert "atlas_performance_local_v5_form_delivery_exact_record($input, $allowed_keys)" in authorization
    assert "method=\"post\"" in render
    assert "wp_nonce_field(" in render
    assert len(re.findall(
        r"ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,\s*false,\s*true",
        render,
    )) == 3
    assert "submit_button('Save disabled configuration', 'primary', '')" in render
    assert "submit_button($label, 'secondary', '')" in render
    assert "'_wp_http_referer'" not in allowlist
    assert "'submit'" not in allowlist
    for forbidden in (
        "register_rest_route",
        "admin_post_nopriv",
        "wp_ajax_nopriv",
        "$_GET['recipient_email']",
        "$_GET['from_email']",
    ):
        assert forbidden not in register + handler + render


def test_05715_admin_page8_email_action_is_server_built_cas_and_route_bound() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    allowlist = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_allowed_keys"
    )
    authorization = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_request_is_authorized",
    )
    candidate = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_candidate",
    )
    apply = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email",
    )
    state = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state",
    )
    configuration_ready = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_configuration_is_ready",
    )
    render = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_render_page"
    )
    assert "$command === 'add_governed_customer_email'" in allowlist
    assert "array_merge($base, ['expected_prior_sha256'])" in allowlist
    assert "preg_match('/^[a-f0-9]{64}$/D', $expected) === 1" in authorization
    assert "count($fields) === 5" in candidate
    assert "count($fields) !== 6" in candidate
    assert "array_slice($fields, 0, 5)" in candidate
    assert "($fields[5] ?? null) !== $governed_email" in candidate
    assert "default_field_contract($fields)" in candidate
    assert "governed_email_field()" in candidate
    assert "atlas_performance_local_v5_payload_is_valid($candidate)" in candidate
    assert "($config['enabled'] ?? null) === false" in configuration_ready
    assert "['reply_to'] ?? null" in configuration_ready
    assert "'enabled' => true" in configuration_ready
    assert "'field_key' => 'email'" in configuration_ready
    assert "governed_field_contract_matches(" in configuration_ready
    assert "configuration_errors(" in configuration_ready
    assert "admin_metadata_upgrade_configuration_is_ready(" in state
    assert "admin_metadata_upgrade_configuration_is_ready(" in apply
    assert "ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_REQUEST_SCHEMA" in apply
    assert "'expected_prior_sha256' => $expected" in apply
    assert "'payload' => $candidate" in apply
    assert "new WP_REST_Request(" in apply
    assert "!function_exists('atlas_performance_local_v5_page_payload_permission')" in apply
    assert "$permission = atlas_performance_local_v5_page_payload_permission($request);" in apply
    assert "if ($permission !== true)" in apply
    assert "page_payload_apply($request)" in apply
    assert "$response->get_status() !== 200" in apply
    assert "exact_record($data" in apply
    assert "ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA" in apply
    assert "ATLAS_METADATA_BRIDGE_VERSION" in apply
    assert "['APPLIED', 'UNCHANGED']" in apply
    assert "$readback !== $candidate || $readback_hash !== $resulting_hash" in apply
    assert "$config_readback !== $config" in apply
    assert "update_post_meta" not in apply
    assert "add_post_meta" not in apply
    assert "delete_post_meta" not in apply
    assert "recipient_email" not in apply
    assert "from_email" not in apply
    assert "metadata_sha256" in state and "target_sha256" in state
    assert 'name="expected_prior_sha256"' in render
    assert "add_governed_customer_email" in render
    assert "<textarea" not in render


def test_05715_page_payload_private_scan_preserves_only_exact_governed_public_contact() -> None:
    source = PAGE_PAYLOAD.read_text(encoding="utf-8")
    envelope = _function(
        source, "atlas_performance_local_v5_page_payload_post_envelope"
    )
    private_scan = _function(
        source,
        "atlas_performance_local_v5_page_payload_contains_private_delivery_value",
    )
    assert "metadata_state($route_post_id)" in envelope
    assert "$current['valid'] && is_array($current['value'])" in envelope
    assert "$body['payload']," in envelope and "$prior_payload" in envelope
    assert "$prior_payload['website']['contact_email']" in private_scan
    assert "$prior_payload['footer']['contact_email']" in private_scan
    assert "$payload['website']['contact_email']" in private_scan
    assert "$payload['footer']['contact_email']" in private_scan
    assert "$recipient === $prior_contact" in private_scan
    assert "$recipient_scan['website']['contact_email'] = null" in private_scan
    assert "$recipient_scan['footer']['contact_email'] = null" in private_scan
    from_scan = private_scan.index("$has_from && str_contains")
    recipient_scrub = private_scan.index("$recipient_scan['website']['contact_email'] = null")
    assert from_scan < recipient_scrub


def test_05715_configuration_is_server_built_disabled_first_and_exactly_one_option() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    target = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_target_payload"
    )
    candidate = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_candidate"
    )
    write = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_write_verified"
    )
    assert "'enabled' => false" in candidate
    for exact_identity in (
        "generated-page:41",
        "composition:41:v10",
        "19f313d10c024cbc988c7cac63e15bb5e7ea78b14c65af243f41e23f5967af32",
        "website:1",
    ):
        assert exact_identity in target
    assert "atlas_performance_local_v5_form_delivery_governed_email_field()" in candidate
    assert "atlas_performance_local_v5_form_delivery_hash_fields(" in candidate
    assert "atlas_performance_local_v5_form_delivery_hash_sixth(" in candidate
    for constant in (
        "ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_TOKEN_TTL_SECONDS",
        "ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_IDEMPOTENCY_TTL_SECONDS",
        "ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_WINDOW_SECONDS",
        "ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_MAX_ATTEMPTS",
    ):
        assert constant in candidate
    for forbidden_input in (
        "website_identity'",
        "field_definition_hash'",
        "definition_hash'",
        "token_ttl_seconds'",
        "idempotency_ttl_seconds'",
        "rate_window_seconds'",
        "rate_max_attempts'",
        "smtp",
        "password",
        "provider",
    ):
        assert f"admin_scalar($input, '{forbidden_input}" not in candidate
    assert write.count("update_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION") == 2
    assert "delete_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION)" in write
    assert "$readback === $candidate" in write
    assert "$restored === $prior" in write
    assert "write_failed_prior_restored" in write
    option_writes = re.findall(r"(?:update|delete|add)_option\(([^,;)]+)", write)
    assert option_writes
    assert set(option_writes) == {"ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION"}


def test_05715_governed_optional_email_and_reply_to_contract_is_exact() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    field = _function(
        source, "atlas_performance_local_v5_form_delivery_governed_email_field"
    )
    for expected in (
        "'field_key' => 'email'",
        "'label' => 'Email'",
        "'required' => false",
        "'control' => 'input'",
        "'input_type' => 'email'",
        "'order' => 6",
        "'maximum_length' => 254",
        "'rule' => 'email_address'",
        "'minimum_length' => 3",
    ):
        assert expected in field
    candidate = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_candidate"
    )
    assert "$reply_to_mode === 'enabled' && $optional_mode !== 'enabled'" in candidate
    assert "'field_key' => $reply_to_mode === 'enabled' ? $governed_email['field_key'] : null" in candidate
    mail = _function(source, "atlas_performance_local_v5_form_delivery_send_mail")
    assert "atlas_performance_local_v5_form_delivery_email($reply_to)" in mail
    assert "$headers[] = 'Reply-To: ' . $reply_to" in mail
    runtime_gate = _function(
        source,
        "atlas_performance_local_v5_form_delivery_governed_field_contract_matches",
    )
    config = _function(
        source, "atlas_performance_local_v5_form_delivery_config_for_payload"
    )
    assert "$fields[5] !== atlas_performance_local_v5_form_delivery_governed_email_field()" in runtime_gate
    assert "['enabled' => true, 'field_key' => 'email']" in runtime_gate
    assert "governed_field_contract_matches(" in config


def test_05715_canonical_domain_exception_is_exact_and_staging_only() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    canonical = _function(
        source, "atlas_performance_local_v5_form_delivery_canonical_website_domain"
    )
    allowed = _function(
        source, "atlas_performance_local_v5_form_delivery_from_domain_is_allowed"
    )
    assert "ATLAS_METADATA_CANONICAL_URL" in canonical
    assert "str_starts_with($host, 'www.')" in canonical
    assert "substr($host, 4)" in canonical
    assert "hash_equals($expected[1], $from_domain)" in allowed
    assert "wp_get_environment_type() !== 'staging'" in allowed
    assert "hash_equals($canonical, $from_domain)" in allowed
    for forbidden in ("str_ends_with", "preg_match($canonical", "HTTP_HOST", "SERVER_NAME"):
        assert forbidden not in allowed


def test_05715_saved_status_and_admin_html_are_redacted_and_replacement_inputs_blank() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    status = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_redacted_status"
    )
    render = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_render_page"
    )
    assert set(re.findall(r"'([a-z_]+)'\s*=>", status)) >= {
        "configured",
        "enabled",
        "schema_valid",
        "field_definition_hash_match",
        "recipient_present",
        "from_present",
        "from_domain_valid",
        "reply_to_mode",
        "optional_sixth_field_mode",
    }
    assert "value=\"\"" in render
    assert "$config['recipient_email']" not in render
    assert "$config['from_email']" not in render
    assert "get_option(" not in render
    assert "=> $config['recipient_email']" not in status
    assert "=> $config['from_email']" not in status
    assert "add_query_arg(" not in render


def test_05715_enable_requires_current_exact_payload_and_disable_preserves_configuration() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    enable = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_enable_candidate"
    )
    disable = _function(
        source, "atlas_performance_local_v5_form_delivery_admin_disable_candidate"
    )
    match = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_field_definition_matches",
    )
    remove = _function(
        source,
        "atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified",
    )
    assert "admin_field_definition_matches(" in enable
    assert "configuration_errors(" in enable
    assert "$candidate['enabled'] = true" in enable
    assert "$candidate = $config" in disable
    assert "$candidate['enabled'] = false" in disable
    assert "delete_option" not in disable
    assert "($payload['form']['fields'] ?? null) === $target_fields" in match
    assert "($prior['enabled'] ?? null) !== false" in remove
    assert "delete_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION)" in remove
    assert "$readback === $sentinel" in remove
    assert "$restored === $prior" in remove


def test_05715_public_surfaces_still_exclude_delivery_configuration() -> None:
    source = DELIVERY.read_text(encoding="utf-8")
    page_payload = PAGE_PAYLOAD.read_text(encoding="utf-8")
    renderer = RENDERER.read_text(encoding="utf-8")
    script = SCRIPT.read_text(encoding="utf-8")
    register_submission = _function(
        source, "atlas_performance_local_v5_form_delivery_register_route"
    )
    public_response = _function(
        source, "atlas_performance_local_v5_form_delivery_safe_response"
    )
    inspect = _function(
        page_payload, "atlas_performance_local_v5_page_payload_inspect"
    )
    assert "register_rest_route(" not in _function(
        source, "atlas_performance_local_v5_form_delivery_admin_register_page"
    )
    assert "register_rest_route(" in register_submission
    for forbidden in ("recipient_email", "from_email", "smtp", "password"):
        assert forbidden not in public_response
        assert forbidden not in inspect
        assert forbidden not in renderer.lower()
        assert forbidden not in script.lower()
