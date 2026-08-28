from __future__ import annotations

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "wordpress/project-atlas-metadata-bridge-0.57.9"
MODULE_PATH = PACKAGE / "includes/performance-local-v5-form-delivery.php"
RENDERER_PATH = PACKAGE / "includes/performance-local-v5-renderer.php"
SCRIPT_PATH = PACKAGE / "assets/performance-local-v5.js"
STYLESHEET_PATH = PACKAGE / "assets/performance-local-v5.css"
MAIN_PATH = PACKAGE / "project-atlas-metadata-bridge.php"

MODULE = MODULE_PATH.read_text(encoding="utf-8")
RENDERER = RENDERER_PATH.read_text(encoding="utf-8")
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")
STYLESHEET = STYLESHEET_PATH.read_text(encoding="utf-8")
MAIN = MAIN_PATH.read_text(encoding="utf-8")

PUBLIC_CONTACT_EMAIL = "public-contact@atlas-v5-site.localhost"
PRIVATE_RECIPIENT_EMAIL = "private-inbox@atlas-v5-mail.localhost"
PRIVATE_FROM_EMAIL = "no-reply@atlas-v5-site.localhost"


def _function(source: str, name: str) -> str:
    match = re.search(rf"function {re.escape(name)}\([^)]*\)(?:\s*:\s*[^{{]+)?\s*{{", source)
    assert match, f"missing {name}"
    depth = 1
    index = match.end()
    while depth and index < len(source):
        depth += (source[index] == "{") - (source[index] == "}")
        index += 1
    assert depth == 0, f"unbalanced {name}"
    return source[match.start():index]


CONFIG = _function(MODULE, "atlas_performance_local_v5_form_delivery_configuration_errors")
TOKEN_ISSUE = _function(MODULE, "atlas_performance_local_v5_form_delivery_issue_token")
TOKEN_SIGNATURE = _function(MODULE, "atlas_performance_local_v5_form_delivery_verify_token_signature")
TOKEN_VALIDATE = _function(MODULE, "atlas_performance_local_v5_form_delivery_validate_token")
ORIGIN = _function(MODULE, "atlas_performance_local_v5_form_delivery_same_origin_request")
PARSE = _function(MODULE, "atlas_performance_local_v5_form_delivery_parse_request")
FIELDS = _function(MODULE, "atlas_performance_local_v5_form_delivery_validate_fields")
NORMALIZE = _function(MODULE, "atlas_performance_local_v5_form_delivery_normalize_value")
SUBMIT = _function(MODULE, "atlas_performance_local_v5_form_delivery_submit")
MAIL = _function(MODULE, "atlas_performance_local_v5_form_delivery_send_mail")
MAIL_BODY = _function(MODULE, "atlas_performance_local_v5_form_delivery_mail_body")
RENDER_FORM = _function(RENDERER, "atlas_performance_local_v5_render_form")
DISABLE_PAGE_CACHE = _function(MODULE, "atlas_performance_local_v5_form_delivery_disable_page_cache")
RENDER_CONTEXT = _function(MODULE, "atlas_performance_local_v5_form_delivery_render_context")
WEBSITE = _function(RENDERER, "atlas_performance_local_v5_website")
FOOTER = _function(RENDERER, "atlas_performance_local_v5_footer")
FINAL_CONVERSION = _function(RENDERER, "atlas_performance_local_v5_render_final_conversion")
RENDER_FOOTER = _function(RENDERER, "atlas_performance_local_v5_render_footer")


def _contains(source: str, *values: str) -> bool:
    return all(value in source for value in values)


CITY_FORM_SCOPE = (
    "body.project-atlas-v5-template "
    ".projectAtlasV5Root.performanceLocalV5CityServicePreview "
    ".performanceLocalFinalCta"
)


CASES: list[tuple[str, callable]] = [
    # Configuration, requirements 1-10.
    ("01_complete_exact_configuration", lambda: _contains(CONFIG, "schema_version", "recipient_email", "optional_sixth_field", "return array_values(array_unique($errors))")),
    ("02_disabled_configuration_is_inert", lambda: "($config['enabled'] ?? null) !== true" in MODULE and "data-atlas-v5-inert-form" in RENDER_FORM),
    ("03_missing_recipient_fails_closed", lambda: "Configuration keys differ from the exact delivery contract." in CONFIG and "Recipient is invalid." in CONFIG),
    ("04_invalid_recipient_fails_closed", lambda: "atlas_performance_local_v5_form_delivery_email($value['recipient_email'])" in CONFIG),
    ("05_invalid_from_identity_fails_closed", lambda: _contains(CONFIG, "From name is invalid.", "From email is invalid.")),
    ("06_from_domain_mismatch_fails_closed", lambda: _contains(CONFIG, "form_delivery_expected_origin", "$website_origin[1]", "From email does not use the governed Website domain.")),
    ("07_unknown_configuration_keys_fail", lambda: "atlas_performance_local_v5_form_delivery_exact_record($value, $keys)" in CONFIG),
    ("08_field_definition_mismatch_fails", lambda: _contains(CONFIG, "field_definition_hash", "Field definition does not match the rendered form.")),
    ("09_website_form_version_mismatch_fails", lambda: _contains(CONFIG, "Website identity does not match", "Form identity differs.", "Form version differs.")),
    ("10_invalid_duration_and_rate_values_fail", lambda: all(value in CONFIG for value in ("[300, 86400]", "[60, 86400]", "[60, 3600]", "[1, 20]"))),
    # Token, requirements 11-22.
    ("11_exact_valid_token_contract", lambda: _contains(TOKEN_ISSUE, "token_schema", "issued_at", "expires_at", "token_identity", "hash_hmac")),
    ("12_missing_token_fails", lambda: "!is_string($body['token']) || $body['token'] === ''" in PARSE),
    ("13_expired_token_fails", lambda: "$claims['expires_at'] <= $now" in TOKEN_VALIDATE),
    ("14_future_issued_token_fails", lambda: "$claims['issued_at'] > $now" in TOKEN_VALIDATE),
    ("15_altered_claim_fails", lambda: "atlas_performance_local_v5_form_delivery_canonical_json($claims)" in TOKEN_SIGNATURE),
    ("16_altered_signature_fails", lambda: "hash_equals($expected, $signature)" in TOKEN_SIGNATURE),
    ("17_wrong_website_token_fails", lambda: "$claims['website_identity'] !== $payload['website']['identity']" in TOKEN_VALIDATE),
    ("18_wrong_page_token_fails", lambda: "$claims['page_identity'] !== atlas_performance_local_v5_form_delivery_page_identity($post_id)" in TOKEN_VALIDATE),
    ("19_wrong_form_token_fails", lambda: "$claims['form_identity'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY" in TOKEN_VALIDATE),
    ("20_wrong_field_hash_token_fails", lambda: "$claims['field_definition_hash'] !== atlas_performance_local_v5_form_delivery_hash_fields" in TOKEN_VALIDATE),
    ("21_extra_token_claim_fails", lambda: "atlas_performance_local_v5_form_delivery_exact_record($claims" in TOKEN_SIGNATURE),
    ("22_malformed_token_fails", lambda: _contains(TOKEN_SIGNATURE, "substr_count($token, '.') !== 1", "base64url_decode", "JSON_THROW_ON_ERROR")),
    # Fields, requirements 23-32.
    ("23_exact_five_field_submission", lambda: "!in_array(count($fields), [5, 6], true)" in MODULE and "$expected_binding = $sixth === null ? null" in CONFIG),
    ("24_valid_governed_sixth_field", lambda: "atlas_performance_local_v5_form_field($fields[5], 5)" in MODULE and "definition_hash" in CONFIG),
    ("25_seventh_customer_field_fails", lambda: "!in_array(count($fields), [5, 6], true)" in MODULE),
    ("26_arbitrary_extra_customer_key_fails", lambda: _contains(FIELDS, "array_keys($values)", "$expected !== $actual")),
    ("27_missing_required_field_fails", lambda: "$field['required'] && $value === ''" in NORMALIZE),
    ("28_overlength_field_fails", lambda: "$length > $field['maximum_length']" in NORMALIZE),
    ("29_invalid_phone_fails", lambda: _contains(NORMALIZE, "$rule === 'phone'", "preg_match_all('/[0-9]/'")),
    ("30_invalid_zip_fails", lambda: _contains(NORMALIZE, "$rule === 'postal_code'", "A-Za-z0-9 -")),
    ("31_invalid_optional_email_fails", lambda: _contains(NORMALIZE, "$rule === 'email_address'", "form_delivery_email($value)") and "form_delivery_sixth_field_is_safe" in MODULE),
    ("32_control_and_header_injection_fails", lambda: _contains(NORMALIZE, "str_contains($value, \"\\n\")", "\\x00-\\x1F\\x7F")),
    # Security and delivery, requirements 33-50.
    ("33_unsafe_origin_fails", lambda: "origin_tuple($origin, false)" in ORIGIN),
    ("34_cross_site_origin_fails", lambda: "$actual === $expected" in ORIGIN),
    ("35_missing_same_origin_proof_fails", lambda: "if (!is_string($referer) || $referer === '') { return false; }" in ORIGIN),
    ("36_honeypot_creates_no_mail", lambda: SUBMIT.index("if ($body['honeypot'] !== '')") < SUBMIT.index("form_delivery_rate_allowed")),
    ("37_rate_limit_creates_no_mail", lambda: SUBMIT.index("form_delivery_rate_allowed") < SUBMIT.index("form_delivery_send_mail")),
    ("38_first_identity_creates_one_mail_path", lambda: SUBMIT.count("atlas_performance_local_v5_form_delivery_send_mail(") == 1),
    ("39_replay_creates_no_second_mail", lambda: SUBMIT.index("$idempotency_status === 'delivered'") < SUBMIT.index("form_delivery_send_mail")),
    ("40_fresh_identity_can_deliver", lambda: _contains(SUBMIT, "claim_idempotency", "mark_delivered")),
    ("41_pending_identity_is_atomic", lambda: _contains(MODULE, "add_option(", "['state' => 'pending', 'expires_at' => $expires_at]")),
    ("42_mail_success_returns_approved_state", lambda: _contains(SUBMIT, "'success'", "$config['success_message']")),
    ("43_mail_failure_is_generic", lambda: _contains(SUBMIT, "'mail_failure'", "$config['failure_message']", "503")),
    ("44_request_scoped_from_is_removed", lambda: all(value in MAIL for value in ("add_filter('wp_mail_from'", "remove_filter('wp_mail_from'", "finally"))),
    ("45_reply_to_absent_by_default", lambda: "$headers = [];" in MAIL and "if ($config['reply_to']['enabled'])" in MAIL),
    ("46_governed_sixth_email_reply_to", lambda: _contains(CONFIG, "email_address", "Reply-To does not match the governed sixth email field.")),
    ("47_customer_input_never_enters_subject", lambda: "function atlas_performance_local_v5_form_delivery_subject" in MODULE and "$fields" not in _function(MODULE, "atlas_performance_local_v5_form_delivery_subject")),
    ("48_system_values_never_enter_body", lambda: all(value not in MAIL_BODY for value in ("token", "idempotency", "honeypot", "REMOTE_ADDR", "HTTP_USER_AGENT"))),
    ("49_customer_values_are_not_persisted", lambda: all(value not in SUBMIT for value in ("update_post_meta", "add_post_meta", "wp_insert_post", "wp_insert_comment"))),
    ("50_only_hash_and_expiry_abuse_metadata", lambda: _contains(MODULE, "form_delivery_metadata_hash", "expires_at", "set_transient") and "REMOTE_ADDR" not in _function(MODULE, "atlas_performance_local_v5_form_delivery_idempotency_option")),
    # Presentation, requirements 51-60.
    ("51_inert_0578_equivalent_branch", lambda: _contains(RENDER_FORM, "data-atlas-v5-inert-form", "readonly", "disabled", "data-collects-data=\"false\"")),
    ("52_enabled_form_reuses_markup_and_order", lambda: RENDER_FORM.count("performanceLocalV5FormGrid") == 1 and RENDER_FORM.count("foreach ($form['fields'] as $field)") == 1 and 'method="post"' in RENDER_FORM),
    ("53_city_and_estimate_share_renderer", lambda: RENDERER.count("atlas_performance_local_v5_render_form($payload['form']") == 2),
    ("54_no_second_form_component", lambda: RENDERER.count("<form") == 1 and RENDERER.count("function atlas_performance_local_v5_render_form") == 1),
    ("55_mobile_fields_stack", lambda: _contains(STYLESHEET, f"@media (max-width: 900px) {{\n  {CITY_FORM_SCOPE} .performanceLocalV5FormGrid", "grid-template-columns: minmax(0, 1fr);")),
    ("56_desktop_fields_balanced", lambda: f"""{CITY_FORM_SCOPE} .performanceLocalV5FormGrid {{
  width: 100%;
  grid-template-columns: repeat(2, minmax(0, 1fr));
}}""" in STYLESHEET),
    ("57_result_status_is_accessible", lambda: _contains(RENDER_FORM, "role=\"status\"", "aria-live=\"polite\"", "tabindex=\"-1\"")),
    ("58_submit_disabled_while_pending", lambda: _contains(SCRIPT, "if (pending) return", "submit.disabled = value", "data-v5-form-pending")),
    ("59_no_browser_storage_write", lambda: all(value not in SCRIPT for value in ("localStorage", "sessionStorage", "indexedDB", "document.cookie"))),
    ("60_no_external_url_in_client", lambda: "http://" not in SCRIPT and "https://" not in SCRIPT and "endpoint.origin !== window.location.origin" in SCRIPT),
    # Final 0.57.9 contact-role and validation-UX corrections, requirements 61-70.
    ("61_public_contact_is_optional", lambda: "$value['contact_email'] === null" in WEBSITE and "$value['contact_email'] === null" in FOOTER),
    ("62_absent_public_email_omits_actions", lambda: "$website['contact_email'] !== null" in FINAL_CONVERSION and "$footer['contact_email'] !== null" in RENDER_FOOTER),
    ("63_private_delivery_never_falls_back_to_public_output", lambda: all(value not in RENDERER + SCRIPT for value in ("recipient_email", "from_email"))),
    ("64_private_recipient_change_cannot_change_render_context", lambda: all(value not in RENDER_CONTEXT for value in ("recipient_email", "from_email", "failure_message", "success_message"))),
    ("65_validation_message_is_fixed_and_distinct", lambda: _contains(MODULE, "Please check the highlighted fields and try again.", "ATLAS_PERFORMANCE_LOCAL_V5_FORM_VALIDATION_MESSAGE") and "ATLAS_PERFORMANCE_LOCAL_V5_FORM_VALIDATION_MESSAGE" in SUBMIT),
    ("66_governed_validation_metadata_is_rendered", lambda: _contains(RENDER_FORM, "novalidate", "data-validation-rule", "data-validation-minimum-length", "data-validation-maximum-length")),
    ("67_validation_marks_and_focuses_first_invalid", lambda: _contains(SCRIPT, 'result.state === "validation_error" ? markValidationErrors() : null', 'setAttribute("aria-invalid", "true")', "return firstInvalid;", "focusFirstInvalid(firstInvalid);", "window.requestAnimationFrame(applyFocus);", 'control.scrollIntoView({ behavior: "auto", block: "center", inline: "nearest" });')),
    ("68_invalid_state_clears_on_field_input", lambda: _contains(SCRIPT, 'form.addEventListener("input"', "clearValidationState(event.target)", 'removeAttribute("aria-invalid")')),
    ("69_mail_failure_does_not_mark_fields_invalid", lambda: SCRIPT.count("markValidationErrors()") == 2 and 'result.state === "validation_error"' in SCRIPT),
    ("70_exact_synthetic_roles_are_distinct_and_nonproduction", lambda: len({PUBLIC_CONTACT_EMAIL, PRIVATE_RECIPIENT_EMAIL, PRIVATE_FROM_EMAIL}) == 3 and all(value not in MODULE + RENDERER + SCRIPT + STYLESHEET + MAIN for value in (PUBLIC_CONTACT_EMAIL, PRIVATE_RECIPIENT_EMAIL, PRIVATE_FROM_EMAIL))),
    # Final 0.57.9 WordPress presentation hardening, requirements 71-78.
    ("71_city_form_owns_full_final_grid_width", lambda: _contains(STYLESHEET, f"{CITY_FORM_SCOPE} .performanceLocalV5Form {{", "width: 100%;", "grid-template-columns: minmax(0, 1fr);", f"{CITY_FORM_SCOPE} .performanceLocalV5Form > .performanceLocalV5FormGrid")),
    ("72_field_text_placeholder_and_caret_contrast", lambda: _contains(STYLESHEET, f'{CITY_FORM_SCOPE} .performanceLocalV5Form :where(input:not([type="hidden"]), textarea)', "background: #f8faf8;", "color: #17231c;", "caret-color: #17231c;", "color: #59675f;")),
    ("73_disabled_and_autofill_contrast", lambda: _contains(STYLESHEET, f'{CITY_FORM_SCOPE} .performanceLocalV5Form :where(input:not([type="hidden"]), textarea):disabled', "background: #e5ebe7;", "-webkit-text-fill-color: #46554d;", f"{CITY_FORM_SCOPE} .performanceLocalV5Form input:-webkit-autofill", "box-shadow: 0 0 0 1000px #f8faf8 inset;")),
    ("74_validation_error_surface_is_legible", lambda: _contains(STYLESHEET, f'{CITY_FORM_SCOPE} .performanceLocalV5Form[data-atlas-v5-active-form] [data-field-key][aria-invalid="true"]', "background: #fff8f6;", "color: #17231c;", f"{CITY_FORM_SCOPE} .performanceLocalV5Form[data-atlas-v5-active-form] .performanceLocalV5FieldError", "background: #fff0ee;", "color: #842c20;")),
    ("75_submit_has_visible_ready_pending_and_focus_states", lambda: _contains(STYLESHEET, f"{CITY_FORM_SCOPE} .performanceLocalV5Form[data-atlas-v5-active-form] > button[data-atlas-v5-form-submit]:not(:disabled)", "border: 2px solid var(--plv5-lime);", "color: var(--plv5-lime-foreground);", "> button[data-atlas-v5-form-submit]:disabled", "background: transparent;", "> button[data-atlas-v5-form-submit]:focus-visible", "outline: 3px solid #fff;")),
    ("76_back_to_top_uses_form_collision_geometry", lambda: _contains(SCRIPT, "formCollisionTargets", "backToTopIntersectsForm", "form.getBoundingClientRect()", "bounds.right >= collisionLeft", "bounds.bottom >= collisionTop", "var formCollision = backToTopIntersectsForm();")),
    ("77_hidden_back_to_top_is_removed_from_interaction", lambda: _contains(SCRIPT, "setBackToTopHidden", 'backToTop.setAttribute("aria-hidden", "true")', "document.activeElement === backToTop", "backToTop.blur()", 'backToTop.removeAttribute("aria-hidden")')),
    ("78_skip_link_starts_hidden_and_is_focus_revealed", lambda: _contains(STYLESHEET, ".performanceLocalV5SkipLink {", "transform: translateY(-180%);", ".performanceLocalV5SkipLink:focus {", "transform: translateY(0);")),
]

assert len(CASES) == 78


@pytest.mark.parametrize(("case_name", "predicate"), CASES, ids=[case[0] for case in CASES])
def test_authorized_form_delivery_requirement(case_name: str, predicate: callable) -> None:
    assert predicate(), case_name


def test_active_form_pages_guarantee_no_store_across_supported_wordpress_versions() -> None:
    assert "define('DONOTCACHEPAGE', true)" in DISABLE_PAGE_CACHE
    assert "nocache_headers();" in DISABLE_PAGE_CACHE
    assert "if (!headers_sent())" in DISABLE_PAGE_CACHE
    assert "Cache-Control: no-cache, must-revalidate, max-age=0, no-store, private" in DISABLE_PAGE_CACHE
