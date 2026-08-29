<?php
declare(strict_types=1);

/**
 * Process-isolated environment-boundary regression for Metadata Bridge 0.57.9.
 *
 * Usage:
 *   php metadata-bridge-0579-environment.php <case> <payloads.json>
 *
 * Each invocation exercises exactly one of: local, staging, development,
 * production, unset, invalid, unavailable. The payload file must be the
 * existing generated Performance Local V5 rehearsal payload list.
 */

final class Atlas_Environment_Test_Failure extends RuntimeException {}

final class WP_Post {
    public string $post_type = 'page';
    public string $post_status = 'publish';
}

final class WP_Error {
    public function __construct(
        private string $code,
        private string $message,
        private array $data = []
    ) {}

    public function get_error_code(): string { return $this->code; }
    public function get_error_message(): string { return $this->message; }
    public function get_error_data(): array { return $this->data; }
}

final class WP_REST_Response {
    private array $headers = [];

    public function __construct(private $data, private int $status = 200) {}

    public function header(string $name, string $value): void {
        $this->headers[strtolower($name)] = $value;
    }

    public function get_data() { return $this->data; }
    public function get_status(): int { return $this->status; }
    public function get_headers(): array { return $this->headers; }
}

final class WP_REST_Request {
    private array $headers = [];
    private string $body = '';

    public function __construct(private string $method = 'GET', private string $route = '') {}

    public function set_header(string $name, string $value): void {
        $this->headers[strtolower($name)] = $value;
    }

    public function get_header(string $name): string {
        return $this->headers[strtolower($name)] ?? '';
    }

    public function set_body(string $body): void { $this->body = $body; }
    public function get_body(): string { return $this->body; }
    public function get_method(): string { return $this->method; }
    public function get_route(): string { return $this->route; }
}

final class WP_REST_Server {
    public const CREATABLE = 'POST';
}

$atlas_case = $argv[1] ?? '';
$atlas_payload_path = $argv[2] ?? '';
$atlas_cases = ['local', 'staging', 'development', 'production', 'unset', 'invalid', 'unavailable'];

if (in_array($atlas_case, $atlas_cases, true) && $atlas_case !== 'unavailable') {
    function wp_get_environment_type(): string {
        $value = getenv('WP_ENVIRONMENT_TYPE');
        return is_string($value) ? $value : '';
    }
}

define('ABSPATH', __DIR__ . '/');

$GLOBALS['atlas_environment_test'] = [
    'case' => $atlas_case,
    'payload' => null,
    'checks' => [],
    'actions' => [],
    'filters' => [],
    'meta_registrations' => [],
    'routes' => [],
    'styles' => [],
    'scripts' => [],
    'script_data' => [],
    'options' => [],
    'transients' => [],
    'scheduled' => [],
    'mail' => [],
];

function atlas_environment_test_check(bool $condition, string $identity): void {
    if (!$condition) { throw new Atlas_Environment_Test_Failure($identity); }
    $GLOBALS['atlas_environment_test']['checks'][] = $identity;
}

function atlas_environment_test_private_leak($value, string $recipient, string $from): bool {
    $encoded = is_string($value)
        ? $value
        : json_encode($value, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    return !is_string($encoded)
        || str_contains($encoded, $recipient)
        || str_contains($encoded, $from);
}

function add_action(string $hook, $callback, int $priority = 10, int $accepted_args = 1): bool {
    $GLOBALS['atlas_environment_test']['actions'][] = compact('hook', 'callback', 'priority', 'accepted_args');
    return true;
}

function add_filter(string $hook, $callback, int $priority = 10, int $accepted_args = 1): bool {
    $GLOBALS['atlas_environment_test']['filters'][$hook][$priority][] = [
        'callback' => $callback,
        'accepted_args' => $accepted_args,
    ];
    return true;
}

function remove_filter(string $hook, $callback, int $priority = 10): bool {
    $entries = $GLOBALS['atlas_environment_test']['filters'][$hook][$priority] ?? [];
    foreach ($entries as $index => $entry) {
        if ($entry['callback'] === $callback) {
            unset($GLOBALS['atlas_environment_test']['filters'][$hook][$priority][$index]);
            return true;
        }
    }
    return false;
}

function apply_filters(string $hook, $value) {
    $priorities = $GLOBALS['atlas_environment_test']['filters'][$hook] ?? [];
    ksort($priorities, SORT_NUMERIC);
    foreach ($priorities as $entries) {
        foreach ($entries as $entry) {
            $value = ($entry['callback'])($value);
        }
    }
    return $value;
}

function register_post_meta(string $post_type, string $meta_key, array $args): bool {
    $GLOBALS['atlas_environment_test']['meta_registrations'][] = compact('post_type', 'meta_key', 'args');
    return true;
}

function register_rest_route(string $namespace, string $route, array $args, bool $override = false): bool {
    $GLOBALS['atlas_environment_test']['routes'][] = compact('namespace', 'route', 'args', 'override');
    return true;
}

function current_user_can(...$unused): bool { return true; }
function is_admin(): bool { return false; }
function wp_doing_ajax(): bool { return false; }
function wp_doing_cron(): bool { return false; }
function is_feed(): bool { return false; }
function is_search(): bool { return false; }
function is_archive(): bool { return false; }
function is_preview(): bool { return false; }
function is_singular(string $post_type = ''): bool { return $post_type === '' || $post_type === 'page'; }
function get_queried_object_id(): int { return 41; }
function get_post(int $post_id) { return $post_id === 41 ? new WP_Post() : null; }
function get_posts(array $unused): array { return [41]; }

function get_post_meta(int $post_id, string $meta_key, bool $single = true) {
    if ($post_id === 41 && $meta_key === '_project_atlas_performance_local_v5_v1') {
        return $GLOBALS['atlas_environment_test']['payload'];
    }
    return $single ? '' : [];
}

function get_option(string $name, $default = false) {
    return array_key_exists($name, $GLOBALS['atlas_environment_test']['options'])
        ? $GLOBALS['atlas_environment_test']['options'][$name]
        : $default;
}

function add_option(string $name, $value, string $deprecated = '', bool $autoload = true): bool {
    if (array_key_exists($name, $GLOBALS['atlas_environment_test']['options'])) { return false; }
    $GLOBALS['atlas_environment_test']['options'][$name] = $value;
    return true;
}

function update_option(string $name, $value, ?bool $autoload = null): bool {
    $GLOBALS['atlas_environment_test']['options'][$name] = $value;
    return true;
}

function delete_option(string $name): bool {
    $exists = array_key_exists($name, $GLOBALS['atlas_environment_test']['options']);
    unset($GLOBALS['atlas_environment_test']['options'][$name]);
    return $exists;
}

function get_transient(string $name) {
    return $GLOBALS['atlas_environment_test']['transients'][$name] ?? false;
}

function set_transient(string $name, $value, int $expiration = 0): bool {
    $GLOBALS['atlas_environment_test']['transients'][$name] = $value;
    return true;
}

function wp_schedule_single_event(int $timestamp, string $hook, array $args = []): bool {
    $GLOBALS['atlas_environment_test']['scheduled'][] = compact('timestamp', 'hook', 'args');
    return true;
}

function home_url(string $path = ''): string {
    return 'https://atlas-environment.test/' . ltrim($path, '/');
}

function rest_url(string $path = ''): string {
    return home_url('wp-json/' . ltrim($path, '/'));
}

function get_permalink(int $post_id): string {
    return $post_id === 41
        ? home_url('drywood-termite-tenting-orlando-fl/')
        : home_url();
}

function get_bloginfo(string $show = ''): string {
    return $show === 'name' ? 'Atlas Environment Test' : '';
}

function plugin_dir_url(string $unused): string {
    return home_url('wp-content/plugins/project-atlas-metadata-bridge/');
}

function wp_enqueue_style(
    string $handle,
    string $src = '',
    array $deps = [],
    $ver = false,
    string $media = 'all'
): void {
    $GLOBALS['atlas_environment_test']['styles'][] = compact('handle', 'src', 'deps', 'ver', 'media');
}

function wp_enqueue_script(
    string $handle,
    string $src = '',
    array $deps = [],
    $ver = false,
    bool $in_footer = false
): void {
    $GLOBALS['atlas_environment_test']['scripts'][] = compact('handle', 'src', 'deps', 'ver', 'in_footer');
}

function wp_script_add_data(string $handle, string $key, $value): bool {
    $GLOBALS['atlas_environment_test']['script_data'][] = compact('handle', 'key', 'value');
    return true;
}

function esc_html(string $value): string {
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function esc_attr(string $value): string { return esc_html($value); }
function esc_url(string $value): string { return esc_attr($value); }

function wp_json_encode($value, int $flags = 0, int $depth = 512) {
    return json_encode($value, $flags, $depth);
}

function wp_check_invalid_utf8(string $value, bool $strip = false): string { return $value; }
function is_email(string $value) { return filter_var($value, FILTER_VALIDATE_EMAIL); }
function wp_parse_url(string $url) { return parse_url($url); }
function wp_salt(string $scheme = 'auth'): string { return 'atlas-environment-test-' . $scheme . '-salt'; }
function wp_timezone(): DateTimeZone { return new DateTimeZone('UTC'); }

function wp_date(string $format, ?int $timestamp = null, ?DateTimeZone $timezone = null): string {
    $date = new DateTimeImmutable('@' . (string) ($timestamp ?? time()));
    return $date->setTimezone($timezone ?? wp_timezone())->format($format);
}

function nocache_headers(): void {}
function is_wp_error($value): bool { return $value instanceof WP_Error; }

function wp_mail($to, string $subject, string $message, $headers = '', array $attachments = []): bool {
    $GLOBALS['atlas_environment_test']['mail'][] = [
        'to' => $to,
        'subject' => $subject,
        'message' => $message,
        'headers' => $headers,
        'attachments' => $attachments,
        'from' => apply_filters('wp_mail_from', 'wordpress' . '@' . 'atlas-environment.test'),
        'from_name' => apply_filters('wp_mail_from_name', 'WordPress'),
        'content_type' => apply_filters('wp_mail_content_type', 'text/plain'),
    ];
    return true;
}

function atlas_environment_test_request(array $body): WP_REST_Request {
    $encoded = json_encode($body, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    atlas_environment_test_check(is_string($encoded), 'request_json_encoded');
    $request = new WP_REST_Request(
        'POST',
        '/project-atlas/v4/performance-local-v5/estimate'
    );
    $request->set_body($encoded);
    $request->set_header('content-type', 'application/json; charset=utf-8');
    $request->set_header('content-length', (string) strlen($encoded));
    $request->set_header('origin', 'https://atlas-environment.test');
    return $request;
}

function atlas_environment_test_request_body(array $payload, array $config, string $token): array {
    return [
        'token' => $token,
        'idempotency_identity' => '11111111-1111-4111-8111-111111111111',
        'website_identity' => $payload['website']['identity'],
        'form_identity' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY,
        'form_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION,
        'page_identity' => 'wordpress-page:41',
        'field_definition_hash' => $config['field_definition_hash'],
        'honeypot' => '',
        'fields' => [
            'name' => 'Environment Test Customer',
            'phone' => '407-555-0123',
            'postal-code' => '32801',
            'requested-service' => 'Drywood termite tenting',
            'message' => 'Please contact the synthetic test customer.',
        ],
    ];
}

try {
    atlas_environment_test_check(in_array($atlas_case, $atlas_cases, true), 'case_is_supported');
    $atlas_environment_input = getenv('WP_ENVIRONMENT_TYPE');
    $atlas_environment_input_matches = match ($atlas_case) {
        'unset', 'unavailable' => $atlas_environment_input === false,
        default => $atlas_environment_input === $atlas_case,
    };
    atlas_environment_test_check($atlas_environment_input_matches, 'environment_input_matches_case');
    atlas_environment_test_check(
        $atlas_case === 'unavailable'
            ? !function_exists('wp_get_environment_type')
            : function_exists('wp_get_environment_type'),
        'environment_function_availability_matches_case'
    );
    atlas_environment_test_check(
        is_string($atlas_payload_path) && $atlas_payload_path !== '' && is_file($atlas_payload_path),
        'payload_file_exists'
    );
    $atlas_payload_raw = file_get_contents($atlas_payload_path);
    atlas_environment_test_check(is_string($atlas_payload_raw) && $atlas_payload_raw !== '', 'payload_file_read');
    $atlas_payload_list = json_decode($atlas_payload_raw, true, 512, JSON_THROW_ON_ERROR);
    atlas_environment_test_check(is_array($atlas_payload_list) && array_is_list($atlas_payload_list), 'payload_list_exact');
    $atlas_payload_matches = array_values(array_filter(
        $atlas_payload_list,
        static fn($value): bool => is_array($value)
            && ($value['payload_identity']['fixture_key'] ?? null) === 'city_service'
    ));
    atlas_environment_test_check(count($atlas_payload_matches) === 1, 'city_service_payload_exactly_one');
    $atlas_payload = $atlas_payload_matches[0];
    $GLOBALS['atlas_environment_test']['payload'] = $atlas_payload;

    $atlas_package = dirname(__DIR__) . '/project-atlas-metadata-bridge-0.57.9';
    $atlas_renderer = $atlas_package . '/includes/performance-local-v5-renderer.php';
    $atlas_delivery = $atlas_package . '/includes/performance-local-v5-form-delivery.php';
    atlas_environment_test_check(is_file($atlas_renderer) && is_file($atlas_delivery), 'contained_modules_exist');
    require $atlas_renderer;
    require $atlas_delivery;

    $atlas_private_recipient = 'recipient' . '@' . 'private-delivery.test';
    $atlas_private_from = 'no-reply' . '@' . 'atlas-environment.test';
    $atlas_public_contact = $atlas_payload['website']['contact_email'] ?? null;
    atlas_environment_test_check(
        is_string($atlas_public_contact)
            && $atlas_public_contact !== $atlas_private_recipient
            && $atlas_public_contact !== $atlas_private_from
            && $atlas_private_recipient !== $atlas_private_from,
        'public_and_private_mail_roles_are_distinct'
    );

    $atlas_config = [
        'schema_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_SCHEMA,
        'enabled' => true,
        'website_identity' => $atlas_payload['website']['identity'],
        'form_identity' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY,
        'form_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION,
        'field_definition_hash' => atlas_performance_local_v5_form_delivery_hash_fields(
            $atlas_payload['form']['fields']
        ),
        'recipient_email' => $atlas_private_recipient,
        'from_name' => 'Atlas Environment Test',
        'from_email' => $atlas_private_from,
        'subject_template' => 'Estimate request for {{company_name}}',
        'success_message' => 'Your estimate request was received.',
        'failure_message' => 'Your estimate request could not be delivered.',
        'token_ttl_seconds' => 900,
        'idempotency_ttl_seconds' => 3600,
        'rate_window_seconds' => 300,
        'rate_max_attempts' => 5,
        'reply_to' => ['enabled' => false, 'field_key' => null],
        'optional_sixth_field' => null,
    ];
    $GLOBALS['atlas_environment_test']['options'][ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION] = $atlas_config;
    $_SERVER['REMOTE_ADDR'] = '192.0.2.41';

    $atlas_expected_allowed = in_array($atlas_case, ['local', 'staging'], true);
    atlas_environment_test_check(
        atlas_performance_local_v5_environment_is_allowed() === $atlas_expected_allowed,
        'central_environment_decision'
    );

    $atlas_validation_errors = atlas_performance_local_v5_validate_payload($atlas_payload);
    atlas_environment_test_check(
        $atlas_expected_allowed ? $atlas_validation_errors === [] : $atlas_validation_errors !== [],
        'payload_environment_boundary'
    );

    atlas_performance_local_v5_register_meta();
    $atlas_meta = $GLOBALS['atlas_environment_test']['meta_registrations'];
    $atlas_default_template = '/theme/default-page.php';
    $atlas_selected_template = atlas_performance_local_v5_template_include($atlas_default_template);
    atlas_performance_local_v5_enqueue_assets();
    $atlas_styles = $GLOBALS['atlas_environment_test']['styles'];
    $atlas_scripts = $GLOBALS['atlas_environment_test']['scripts'];
    $atlas_script_data = $GLOBALS['atlas_environment_test']['script_data'];

    $atlas_public_payload = atlas_performance_local_v5_current_payload();
    ob_start();
    if (is_array($atlas_public_payload)) {
        atlas_performance_local_v5_render_page($atlas_public_payload);
    }
    $atlas_rendered = (string) ob_get_clean();

    atlas_performance_local_v5_form_delivery_register_route();
    $atlas_routes = $GLOBALS['atlas_environment_test']['routes'];
    $atlas_context = atlas_performance_local_v5_form_delivery_render_context($atlas_payload['form']);

    if ($atlas_expected_allowed) {
        atlas_environment_test_check(count($atlas_meta) === 1, 'allowed_meta_registered_once');
        $atlas_meta_entry = $atlas_meta[0];
        atlas_environment_test_check(
            $atlas_meta_entry['post_type'] === 'page'
                && $atlas_meta_entry['meta_key'] === ATLAS_PERFORMANCE_LOCAL_V5_META_KEY
                && ($atlas_meta_entry['args']['show_in_rest'] ?? null) === false,
            'allowed_meta_registration_exact'
        );
        $atlas_sanitizer = $atlas_meta_entry['args']['sanitize_callback'] ?? null;
        atlas_environment_test_check(
            is_callable($atlas_sanitizer) && $atlas_sanitizer($atlas_payload) === $atlas_payload,
            'allowed_meta_sanitizer_accepts_payload'
        );
        atlas_environment_test_check(
            atlas_performance_local_v5_current_payload() === $atlas_payload,
            'allowed_current_payload_exact'
        );
        atlas_environment_test_check(
            $atlas_selected_template === ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE,
            'allowed_template_selected'
        );
        atlas_environment_test_check(
            count($atlas_styles) === 1
                && $atlas_styles[0]['handle'] === 'project-atlas-performance-local-v5'
                && str_ends_with($atlas_styles[0]['src'], '/assets/performance-local-v5.css')
                && $atlas_styles[0]['ver'] === hash_file('sha256', ATLAS_PERFORMANCE_LOCAL_V5_STYLESHEET),
            'allowed_stylesheet_exact'
        );
        atlas_environment_test_check(
            count($atlas_scripts) === 1
                && $atlas_scripts[0]['handle'] === 'project-atlas-performance-local-v5'
                && str_ends_with($atlas_scripts[0]['src'], '/assets/performance-local-v5.js')
                && $atlas_scripts[0]['ver'] === hash_file('sha256', ATLAS_PERFORMANCE_LOCAL_V5_SCRIPT)
                && $atlas_scripts[0]['in_footer'] === true
                && $atlas_script_data === [[
                    'handle' => 'project-atlas-performance-local-v5',
                    'key' => 'strategy',
                    'value' => 'defer',
                ]],
            'allowed_script_exact'
        );
        atlas_environment_test_check(
            str_contains($atlas_rendered, 'data-project-atlas-v5-root')
                && str_contains($atlas_rendered, esc_html($atlas_payload['page']['h1']))
                && str_contains($atlas_rendered, 'data-atlas-v5-active-form')
                && str_contains($atlas_rendered, $atlas_public_contact),
            'allowed_page_and_active_form_rendered'
        );
        atlas_environment_test_check(
            !atlas_environment_test_private_leak(
                $atlas_rendered,
                $atlas_private_recipient,
                $atlas_private_from
            ),
            'allowed_render_has_no_private_mail_identity'
        );
        atlas_environment_test_check(count($atlas_routes) === 1, 'allowed_route_registered_once');
        $atlas_route = $atlas_routes[0];
        atlas_environment_test_check(
            $atlas_route['namespace'] === ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE_NAMESPACE
                && $atlas_route['route'] === ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE
                && ($atlas_route['args']['methods'] ?? null) === WP_REST_Server::CREATABLE
                && ($atlas_route['args']['permission_callback'] ?? null)
                    === 'atlas_performance_local_v5_form_delivery_permission'
                && ($atlas_route['args']['callback'] ?? null)
                    === 'atlas_performance_local_v5_form_delivery_submit',
            'allowed_route_contract_exact'
        );
        atlas_environment_test_check(
            is_array($atlas_context)
                && ($atlas_context['endpoint'] ?? null)
                    === rest_url(ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE_NAMESPACE . ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE)
                && is_string($atlas_context['token'] ?? null),
            'allowed_form_render_context'
        );

        $atlas_request_body = atlas_environment_test_request_body(
            $atlas_payload,
            $atlas_config,
            $atlas_context['token']
        );
        $atlas_response = atlas_performance_local_v5_form_delivery_submit(
            atlas_environment_test_request($atlas_request_body)
        );
        atlas_environment_test_check(
            $atlas_response instanceof WP_REST_Response
                && $atlas_response->get_status() === 200
                && $atlas_response->get_data() === [
                    'ok' => true,
                    'state' => 'success',
                    'message' => $atlas_config['success_message'],
                ],
            'allowed_protected_submission_succeeds'
        );
        $atlas_mail = $GLOBALS['atlas_environment_test']['mail'];
        atlas_environment_test_check(count($atlas_mail) === 1, 'allowed_mail_intercepted_once');
        $atlas_mail_call = $atlas_mail[0];
        atlas_environment_test_check(
            $atlas_mail_call['to'] === $atlas_private_recipient
                && $atlas_mail_call['from'] === $atlas_private_from
                && $atlas_mail_call['from_name'] === $atlas_config['from_name']
                && $atlas_mail_call['content_type'] === 'text/plain'
                && $atlas_mail_call['headers'] === [],
            'allowed_private_mail_routing_exact'
        );
        atlas_environment_test_check(
            !str_contains($atlas_mail_call['subject'], $atlas_private_recipient)
                && !str_contains($atlas_mail_call['subject'], $atlas_private_from)
                && !str_contains($atlas_mail_call['message'], $atlas_private_recipient)
                && !str_contains($atlas_mail_call['message'], $atlas_private_from),
            'allowed_private_values_absent_from_subject_and_body'
        );
        atlas_environment_test_check(
            !atlas_environment_test_private_leak(
                $atlas_response->get_data(),
                $atlas_private_recipient,
                $atlas_private_from
            ),
            'allowed_public_response_has_no_private_mail_identity'
        );
        foreach (['wp_mail_from', 'wp_mail_from_name', 'wp_mail_content_type'] as $atlas_mail_filter) {
            $atlas_entries = array_filter(
                $GLOBALS['atlas_environment_test']['filters'][$atlas_mail_filter][999] ?? []
            );
            atlas_environment_test_check($atlas_entries === [], 'allowed_' . $atlas_mail_filter . '_filter_removed');
        }
    } else {
        atlas_environment_test_check($atlas_meta === [], 'denied_meta_not_registered');
        atlas_environment_test_check(
            atlas_performance_local_v5_current_payload() === null,
            'denied_current_payload_absent'
        );
        atlas_environment_test_check(
            $atlas_selected_template === $atlas_default_template,
            'denied_template_unchanged'
        );
        atlas_environment_test_check(
            $atlas_styles === [] && $atlas_scripts === [] && $atlas_script_data === [],
            'denied_assets_not_enqueued'
        );
        atlas_environment_test_check($atlas_rendered === '', 'denied_render_is_empty');
        atlas_environment_test_check($atlas_routes === [], 'denied_route_not_registered');
        atlas_environment_test_check($atlas_context === null, 'denied_form_context_absent');

        $atlas_denied_token = atlas_performance_local_v5_form_delivery_issue_token(
            $atlas_payload,
            41,
            $atlas_config
        );
        atlas_environment_test_check(is_string($atlas_denied_token), 'denied_signed_token_fixture_created');
        $atlas_denied_result = atlas_performance_local_v5_form_delivery_submit(
            atlas_environment_test_request(
                atlas_environment_test_request_body(
                    $atlas_payload,
                    $atlas_config,
                    $atlas_denied_token
                )
            )
        );
        atlas_environment_test_check(
            $atlas_denied_result instanceof WP_Error
                && $atlas_denied_result->get_error_code() === 'atlas_v5_estimate_request_rejected'
                && ($atlas_denied_result->get_error_data()['status'] ?? null) === 403,
            'denied_protected_submission_rejected'
        );
        atlas_environment_test_check(
            $GLOBALS['atlas_environment_test']['mail'] === [],
            'denied_mail_not_called'
        );
        $atlas_denied_public_surfaces = [
            'validation_errors' => $atlas_validation_errors,
            'rendered' => $atlas_rendered,
            'routes' => $atlas_routes,
            'error_code' => $atlas_denied_result->get_error_code(),
            'error_message' => $atlas_denied_result->get_error_message(),
            'error_data' => $atlas_denied_result->get_error_data(),
        ];
        atlas_environment_test_check(
            !atlas_environment_test_private_leak(
                $atlas_denied_public_surfaces,
                $atlas_private_recipient,
                $atlas_private_from
            ),
            'denied_public_surfaces_have_no_private_mail_identity'
        );
    }

    $atlas_result = [
        'status' => 'PASS',
        'case' => $atlas_case,
        'allowed' => $atlas_expected_allowed,
        'payload_sha256' => hash('sha256', $atlas_payload_raw),
        'checks' => $GLOBALS['atlas_environment_test']['checks'],
        'meta_registration_count' => count($GLOBALS['atlas_environment_test']['meta_registrations']),
        'route_count' => count($GLOBALS['atlas_environment_test']['routes']),
        'mail_count' => count($GLOBALS['atlas_environment_test']['mail']),
    ];
    $atlas_result_json = json_encode(
        $atlas_result,
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
    );
    atlas_environment_test_check(
        !str_contains($atlas_result_json, $atlas_private_recipient)
            && !str_contains($atlas_result_json, $atlas_private_from),
        'sanitized_result_has_no_private_mail_identity'
    );
    $atlas_result['checks'] = $GLOBALS['atlas_environment_test']['checks'];
    echo json_encode(
        $atlas_result,
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE | JSON_THROW_ON_ERROR
    ) . "\n";
    exit(0);
} catch (Atlas_Environment_Test_Failure $error) {
    fwrite(STDERR, json_encode([
        'status' => 'FAIL',
        'case' => in_array($atlas_case, $atlas_cases, true) ? $atlas_case : 'invalid-case',
        'failed_check' => $error->getMessage(),
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
    exit(1);
} catch (Throwable $error) {
    fwrite(STDERR, json_encode([
        'status' => 'FAIL',
        'case' => in_array($atlas_case, $atlas_cases, true) ? $atlas_case : 'invalid-case',
        'failed_check' => 'internal_harness_error',
    ], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . "\n");
    exit(1);
}
