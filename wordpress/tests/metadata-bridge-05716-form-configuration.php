<?php
declare(strict_types=1);

/**
 * Process-local contract proof for the Metadata Bridge 0.57.16 private form
 * configuration surface. All addresses are synthetic fixtures.
 *
 * Usage:
 *   php wordpress/tests/metadata-bridge-05716-form-configuration.php
 */

final class Atlas_Form_Configuration_Test_Failure extends RuntimeException {}

final class WP_Post {
    public string $post_type = 'page';
    public string $post_status = 'publish';
}

final class WP_Error {
    public function __construct(public string $code) {}
}

final class WP_REST_Request {
    private array $url_params = [];
    private array $headers = [];
    private string $body = '';

    public function __construct(
        private string $method = 'GET',
        private string $route = ''
    ) {}
    public function set_url_params(array $params): void { $this->url_params = $params; }
    public function set_header(string $name, string $value): void {
        $this->headers[strtolower($name)] = $value;
    }
    public function set_body(string $body): void { $this->body = $body; }
    public function get_json_params(): array {
        $decoded = json_decode($this->body, true);
        return is_array($decoded) ? $decoded : [];
    }
    public function get_body(): string { return $this->body; }
    public function get_method(): string { return $this->method; }
    public function get_route(): string { return $this->route; }
    public function get_url_params(): array { return $this->url_params; }
}

final class WP_REST_Response {
    private array $headers = [];

    public function __construct(private $data, private int $status = 200) {}
    public function header(string $name, string $value): void {
        $this->headers[strtolower($name)] = $value;
    }
    public function get_data() { return $this->data; }
    public function get_status(): int { return $this->status; }
}

final class WP_REST_Server {
    public const CREATABLE = 'POST';
}

define('ABSPATH', __DIR__ . '/');
define('ATLAS_METADATA_POST_ID', 8);
define('ATLAS_PERFORMANCE_LOCAL_V5_META_KEY', '_project_atlas_performance_local_v5_v1');
define(
    'ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_REQUEST_SCHEMA',
    'project-atlas-performance-local-v5-page-payload-request@1'
);
define(
    'ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA',
    'project-atlas-performance-local-v5-page-payload-route@1'
);
define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.16');
define('ATLAS_METADATA_CANONICAL_URL', 'https://www.canonical.example/service/');

$GLOBALS['atlas_form_configuration_test'] = [
    'checks' => [],
    'environment' => 'staging',
    'is_admin' => true,
    'can_manage' => true,
    'nonce_result' => 1,
    'options' => [],
    'option_writes' => [],
    'corrupt_next_update' => false,
    'delete_mode' => 'normal',
    'payload' => null,
    'admin_pages' => [],
    'actions' => [],
    'page_payload_apply_calls' => [],
    'page_payload_apply_mode' => 'applied',
    'page_payload_permission_mode' => 'allowed',
];

function atlas_form_configuration_test_check(bool $condition, string $identity): void {
    if (!$condition) { throw new Atlas_Form_Configuration_Test_Failure($identity); }
    $GLOBALS['atlas_form_configuration_test']['checks'][] = $identity;
}

function add_action(string $hook, $callback, int $priority = 10, int $accepted_args = 1): bool {
    $GLOBALS['atlas_form_configuration_test']['actions'][] = compact(
        'hook', 'callback', 'priority', 'accepted_args'
    );
    return true;
}

function add_options_page(
    string $page_title,
    string $menu_title,
    string $capability,
    string $menu_slug,
    $callback
) {
    $GLOBALS['atlas_form_configuration_test']['admin_pages'][] = compact(
        'page_title', 'menu_title', 'capability', 'menu_slug', 'callback'
    );
    return $menu_slug;
}

function atlas_performance_local_v5_environment_is_allowed(): bool {
    return in_array(wp_get_environment_type(), ['local', 'staging'], true);
}

function atlas_performance_local_v5_exact_record($value, array $expected_keys): bool {
    if (!is_array($value) || array_is_list($value)) { return false; }
    $actual = array_keys($value);
    sort($actual, SORT_STRING);
    sort($expected_keys, SORT_STRING);
    return $actual === $expected_keys;
}

function atlas_performance_local_v5_form_field($value, int $position): bool {
    return $position === 5
        && is_array($value)
        && atlas_performance_local_v5_exact_record($value, [
            'field_key', 'label', 'required', 'control', 'input_type', 'order',
            'maximum_length', 'validation',
        ])
        && is_string($value['field_key'])
        && is_string($value['label'])
        && is_bool($value['required'])
        && ($value['order'] ?? null) === 6
        && is_int($value['maximum_length'])
        && atlas_performance_local_v5_exact_record(
            $value['validation'] ?? null,
            ['rule', 'minimum_length', 'maximum_length']
        )
        && ($value['validation']['maximum_length'] ?? null) === $value['maximum_length'];
}

function atlas_performance_local_v5_payload_is_valid($payload): bool {
    return is_array($payload)
        && ($payload['surface'] ?? null) === 'city_service'
        && is_string($payload['website']['identity'] ?? null)
        && is_string($payload['website']['company_name'] ?? null)
        && is_string($payload['page']['title'] ?? null)
        && is_array($payload['form']['fields'] ?? null)
        && array_is_list($payload['form']['fields'])
        && in_array(count($payload['form']['fields']), [5, 6], true);
}

function wp_get_environment_type(): string {
    return $GLOBALS['atlas_form_configuration_test']['environment'];
}

function is_admin(): bool { return $GLOBALS['atlas_form_configuration_test']['is_admin']; }

function current_user_can(string $capability, ...$args): bool {
    if ($capability === 'manage_options') {
        return $GLOBALS['atlas_form_configuration_test']['can_manage'];
    }
    return $capability === 'edit_post'
        && ($args[0] ?? null) === ATLAS_METADATA_POST_ID
        && $GLOBALS['atlas_form_configuration_test']['can_manage'];
}

function wp_verify_nonce(string $nonce, string $action) {
    if ($nonce !== 'valid-nonce'
        || $action !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION) {
        return false;
    }
    return $GLOBALS['atlas_form_configuration_test']['nonce_result'];
}

function wp_unslash($value) { return $value; }

function wp_json_encode($value, int $flags = 0, int $depth = 512) {
    return json_encode($value, $flags, $depth);
}

function wp_generate_uuid4(): string {
    return '12345678-1234-4123-8123-123456789abc';
}

function is_wp_error($value): bool { return $value instanceof WP_Error; }

function rest_ensure_response($value): WP_REST_Response {
    return $value instanceof WP_REST_Response ? $value : new WP_REST_Response($value);
}

function wp_check_invalid_utf8(string $value, bool $strip = false): string { return $value; }
function is_email(string $value) { return filter_var($value, FILTER_VALIDATE_EMAIL); }
function wp_parse_url(string $url) { return parse_url($url); }

function home_url(string $path = ''): string {
    return 'https://stage.example.test/' . ltrim($path, '/');
}

function get_bloginfo(string $show = ''): string {
    return $show === 'name' ? 'Synthetic Site' : '';
}

function atlas_performance_local_v5_current_payload(): ?array {
    $payload = $GLOBALS['atlas_form_configuration_test']['payload'];
    return is_array($payload) ? $payload : null;
}

function get_queried_object_id(): int { return ATLAS_METADATA_POST_ID; }

function rest_url(string $path = ''): string {
    return home_url('wp-json/' . ltrim($path, '/'));
}

function get_post(int $post_id) { return $post_id === ATLAS_METADATA_POST_ID ? new WP_Post() : null; }

function get_post_meta(int $post_id, string $key, bool $single = true) {
    return $post_id === ATLAS_METADATA_POST_ID && $key === ATLAS_PERFORMANCE_LOCAL_V5_META_KEY
        ? $GLOBALS['atlas_form_configuration_test']['payload']
        : ($single ? '' : []);
}

function atlas_form_configuration_test_canonicalize($value) {
    if (!is_array($value)) { return $value; }
    if (!array_is_list($value)) { ksort($value, SORT_STRING); }
    foreach ($value as $key => $child) {
        $value[$key] = atlas_form_configuration_test_canonicalize($child);
    }
    return $value;
}

function atlas_performance_local_v5_page_payload_sha256($value): ?string {
    $encoded = wp_json_encode(
        atlas_form_configuration_test_canonicalize($value),
        JSON_UNESCAPED_SLASHES
            | JSON_UNESCAPED_UNICODE
            | JSON_UNESCAPED_LINE_TERMINATORS
            | JSON_PRESERVE_ZERO_FRACTION
    );
    return is_string($encoded) ? hash('sha256', $encoded) : null;
}

function atlas_performance_local_v5_page_payload_permission(
    WP_REST_Request $request
) {
    if ($GLOBALS['atlas_form_configuration_test']['page_payload_permission_mode']
        === 'denied') {
        return new WP_Error('synthetic_permission_denied');
    }
    $params = $request->get_url_params();
    return wp_get_environment_type() === 'staging'
        && current_user_can('manage_options')
        && current_user_can('edit_post', ATLAS_METADATA_POST_ID)
        && ($params['post_id'] ?? null) === (string) ATLAS_METADATA_POST_ID;
}

function atlas_performance_local_v5_page_payload_apply(
    WP_REST_Request $request
) {
    $body = $request->get_json_params();
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'][] = [
        'method' => $request->get_method(),
        'route' => $request->get_route(),
        'params' => $request->get_url_params(),
        'body' => $body,
    ];
    $mode = $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'];
    if ($mode === 'error') { return new WP_Error('synthetic_route_error'); }
    $prior = $GLOBALS['atlas_form_configuration_test']['payload'];
    $prior_hash = atlas_performance_local_v5_page_payload_sha256($prior);
    $payload = $body['payload'] ?? null;
    $resulting_hash = atlas_performance_local_v5_page_payload_sha256($payload);
    if (($body['expected_prior_sha256'] ?? null) !== $prior_hash
        || !is_array($payload)) {
        return new WP_Error('synthetic_stale_or_invalid');
    }
    if ($mode !== 'no_readback') {
        $GLOBALS['atlas_form_configuration_test']['payload'] = $payload;
    }
    $response = [
        'route_schema' => 'project-atlas-performance-local-v5-page-payload-route@1',
        'metadata_bridge_version' => '0.57.16',
        'status' => $mode === 'unchanged' ? 'UNCHANGED' : 'APPLIED',
        'post_id' => ATLAS_METADATA_POST_ID,
        'prior_sha256' => $prior_hash,
        'resulting_sha256' => $mode === 'wrong_hash' ? str_repeat('0', 64) : $resulting_hash,
        'website_id' => $body['website_id'] ?? null,
        'planned_page_id' => $body['planned_page_id'] ?? null,
        'generated_page_id' => $body['generated_page_id'] ?? null,
        'request_identity' => $body['request_identity'] ?? null,
        'metadata_valid' => true,
    ];
    if ($mode === 'extra_response') { $response['unexpected'] = true; }
    if ($mode === 'config_race') {
        $config = $GLOBALS['atlas_form_configuration_test']['options'][
            ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
        ];
        $config['enabled'] = true;
        $GLOBALS['atlas_form_configuration_test']['options'][
            ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
        ] = $config;
    }
    return new WP_REST_Response($response, $mode === 'wrong_status' ? 202 : 200);
}

function get_option(string $name, $default = false) {
    return array_key_exists($name, $GLOBALS['atlas_form_configuration_test']['options'])
        ? $GLOBALS['atlas_form_configuration_test']['options'][$name]
        : $default;
}

function update_option(string $name, $value, ?bool $autoload = null): bool {
    $GLOBALS['atlas_form_configuration_test']['option_writes'][] = ['update', $name, $autoload];
    if ($GLOBALS['atlas_form_configuration_test']['corrupt_next_update']) {
        $GLOBALS['atlas_form_configuration_test']['corrupt_next_update'] = false;
        $GLOBALS['atlas_form_configuration_test']['options'][$name] = ['corrupt' => true];
    } else {
        $GLOBALS['atlas_form_configuration_test']['options'][$name] = $value;
    }
    return true;
}

function delete_option(string $name): bool {
    $GLOBALS['atlas_form_configuration_test']['option_writes'][] = ['delete', $name, null];
    $exists = array_key_exists($name, $GLOBALS['atlas_form_configuration_test']['options']);
    $mode = $GLOBALS['atlas_form_configuration_test']['delete_mode'];
    $GLOBALS['atlas_form_configuration_test']['delete_mode'] = 'normal';
    if ($mode === 'retain_prior') { return false; }
    if ($mode === 'corrupt_residual') {
        $GLOBALS['atlas_form_configuration_test']['options'][$name] = ['corrupt' => true];
        return $exists;
    }
    unset($GLOBALS['atlas_form_configuration_test']['options'][$name]);
    return $exists;
}

function admin_url(string $path = ''): string {
    return 'https://stage.example.test/wp-admin/' . ltrim($path, '/');
}

function esc_html(string $value): string {
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function esc_attr(string $value): string { return esc_html($value); }
function esc_url(string $value): string { return esc_attr($value); }

function wp_nonce_field(
    string $action = '-1',
    string $name = '_wpnonce',
    bool $referer = true,
    bool $display = true
): string {
    $html = '<input type="hidden" name="' . esc_attr($name)
        . '" value="valid-nonce">';
    if ($referer) {
        $html .= '<input type="hidden" name="_wp_http_referer" value="/synthetic/">';
    }
    if ($display) { echo $html; }
    return $html;
}

function submit_button(
    ?string $text = null,
    string $type = 'primary large',
    $name = 'submit',
    bool $wrap = true,
    $other_attributes = null
): void {
    $button = '<input type="submit" class="button ' . esc_attr($type) . '"'
        . ($name ? ' name="' . esc_attr((string) $name) . '"' : '')
        . ' value="' . esc_attr($text ?? 'Save Changes') . '">';
    echo $wrap ? '<p class="submit">' . $button . '</p>' : $button;
}

function wp_die($message = '', $title = '', $args = []): void {
    throw new Atlas_Form_Configuration_Test_Failure('unexpected_wp_die');
}

function wp_safe_redirect(string $location): bool { return true; }

function add_query_arg(array $args, string $url): string {
    return $url . '?' . http_build_query($args, '', '&', PHP_QUERY_RFC3986);
}

function atlas_form_configuration_test_fields(): array {
    return [
        ['field_key' => 'name', 'label' => 'Name', 'required' => true, 'control' => 'input', 'input_type' => 'text', 'order' => 1, 'maximum_length' => 100, 'validation' => ['rule' => 'nonempty_text', 'minimum_length' => 1, 'maximum_length' => 100]],
        ['field_key' => 'phone', 'label' => 'Phone', 'required' => true, 'control' => 'input', 'input_type' => 'tel', 'order' => 2, 'maximum_length' => 40, 'validation' => ['rule' => 'phone', 'minimum_length' => 6, 'maximum_length' => 40]],
        ['field_key' => 'postal-code', 'label' => 'ZIP code', 'required' => true, 'control' => 'input', 'input_type' => 'text', 'order' => 3, 'maximum_length' => 12, 'validation' => ['rule' => 'postal_code', 'minimum_length' => 5, 'maximum_length' => 12]],
        ['field_key' => 'requested-service', 'label' => 'Requested service', 'required' => true, 'control' => 'input', 'input_type' => 'text', 'order' => 4, 'maximum_length' => 160, 'validation' => ['rule' => 'nonempty_text', 'minimum_length' => 1, 'maximum_length' => 160]],
        ['field_key' => 'message', 'label' => 'Optional message', 'required' => false, 'control' => 'textarea', 'input_type' => 'text', 'order' => 5, 'maximum_length' => 2000, 'validation' => ['rule' => 'free_text', 'minimum_length' => 0, 'maximum_length' => 2000]],
    ];
}

function atlas_form_configuration_test_payload(array $fields): array {
    return [
        'surface' => 'city_service',
        'payload_identity' => [
            'source_page' => 'generated-page:41',
            'source_composition' => 'composition:41:v10',
            'source_hash' => '19f313d10c024cbc988c7cac63e15bb5e7ea78b14c65af243f41e23f5967af32',
        ],
        'website' => [
            'identity' => 'website:1',
            'company_name' => 'Synthetic Company',
        ],
        'page' => ['title' => 'Synthetic Service Page'],
        'form' => ['fields' => $fields],
    ];
}

try {
    $module = dirname(__DIR__)
        . '/project-atlas-metadata-bridge-0.57.16/includes/performance-local-v5-form-delivery.php';
    atlas_form_configuration_test_check(is_file($module), 'module_exists');
    require $module;

    $five_fields = atlas_form_configuration_test_fields();
    $GLOBALS['atlas_form_configuration_test']['payload'] = atlas_form_configuration_test_payload(
        $five_fields
    );
    $private_recipient = 'recipient' . '@' . 'private.example';
    $private_from = 'sender' . '@' . 'canonical.example';
    $home_from = 'sender' . '@' . 'stage.example.test';

    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_from_domain_is_allowed($private_from),
        'canonical_domain_allowed_on_staging'
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_from_domain_is_allowed($home_from),
        'exact_home_domain_allowed_on_staging'
    );
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_from_domain_is_allowed(
            'sender' . '@' . 'sub.canonical.example'
        ) && !atlas_performance_local_v5_form_delivery_from_domain_is_allowed(
            'sender' . '@' . 'unrelated.example'
        ),
        'suffix_and_unrelated_domains_rejected'
    );
    $GLOBALS['atlas_form_configuration_test']['environment'] = 'local';
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_from_domain_is_allowed($private_from)
            && atlas_performance_local_v5_form_delivery_from_domain_is_allowed($home_from),
        'canonical_exception_is_staging_only'
    );
    $GLOBALS['atlas_form_configuration_test']['environment'] = 'staging';

    $input = [
        'action' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION,
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD => 'valid-nonce',
        'atlas_command' => 'replace_configuration',
        'recipient_email' => $private_recipient,
        'from_name' => 'Synthetic Website',
        'from_email' => $private_from,
        'subject_template' => 'Estimate request — {{page_title}}',
        'success_message' => 'The synthetic request was sent.',
        'failure_message' => 'The synthetic request could not be sent.',
        'optional_sixth_field_mode' => 'enabled',
        'reply_to_mode' => 'enabled',
    ];
    $_SERVER['REQUEST_METHOD'] = 'POST';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input),
        'exact_rendered_replace_request_authorized'
    );
    $GLOBALS['atlas_form_configuration_test']['nonce_result'] = 2;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input),
        'second_nonce_tick_is_valid'
    );
    $GLOBALS['atlas_form_configuration_test']['nonce_result'] = 1;
    $extra_input = $input;
    $extra_input['unexpected'] = 'value';
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($extra_input),
        'unknown_post_field_rejected'
    );
    $missing_nonce = $input;
    unset($missing_nonce[ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD]);
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($missing_nonce),
        'missing_nonce_rejected'
    );
    $invalid_nonce = $input;
    $invalid_nonce[ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD] = 'invalid';
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($invalid_nonce),
        'invalid_nonce_rejected'
    );
    $GLOBALS['atlas_form_configuration_test']['can_manage'] = false;
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input),
        'wrong_capability_rejected'
    );
    $GLOBALS['atlas_form_configuration_test']['can_manage'] = true;
    $_SERVER['REQUEST_METHOD'] = 'GET';
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input),
        'get_cannot_mutate'
    );
    $_SERVER['REQUEST_METHOD'] = 'POST';

    $candidate = atlas_performance_local_v5_form_delivery_admin_candidate($input);
    atlas_form_configuration_test_check(
        is_array($candidate)
            && $candidate['enabled'] === false
            && $candidate['recipient_email'] === $private_recipient
            && $candidate['from_email'] === $private_from
            && $candidate['token_ttl_seconds'] === 900
            && $candidate['idempotency_ttl_seconds'] === 3600
            && $candidate['rate_window_seconds'] === 300
            && $candidate['rate_max_attempts'] === 5
            && $candidate['reply_to'] === ['enabled' => true, 'field_key' => 'email']
            && ($candidate['optional_sixth_field']['field_key'] ?? null) === 'email'
            && atlas_performance_local_v5_form_delivery_configuration_errors($candidate) === [],
        'valid_candidate_server_built_disabled_first'
    );
    atlas_form_configuration_test_check(
        !array_key_exists('smtp', $candidate)
            && !array_key_exists('password', $candidate)
            && !array_key_exists('provider', $candidate),
        'transport_credentials_cannot_enter_option'
    );

    foreach ([
        ['recipient_email', 'invalid'],
        ['recipient_email', "header\n" . $private_recipient],
        ['from_email', 'malformed-address'],
        ['from_email', 'sender' . '@' . 'unrelated.example'],
        ['from_email', "sender\n" . '@' . 'canonical.example'],
        ['from_name', "Synthetic\nWebsite"],
        ['subject_template', 'Estimate {{unknown_token}}'],
        ['success_message', 'Unsafe <message>'],
        ['failure_message', "Unsafe\nmessage"],
    ] as [$key, $value]) {
        $invalid = $input;
        $invalid[$key] = $value;
        atlas_form_configuration_test_check(
            atlas_performance_local_v5_form_delivery_admin_candidate($invalid) === null,
            'invalid_candidate_' . $key
        );
    }
    $reply_without_email = $input;
    $reply_without_email['optional_sixth_field_mode'] = 'disabled';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_candidate($reply_without_email) === null,
        'reply_to_requires_governed_email_field'
    );

    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $candidate;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_enable_candidate() === null,
        'enable_rejected_before_payload_exactly_matches'
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_config_for_payload(
            $GLOBALS['atlas_form_configuration_test']['payload']
        ) === null
            && atlas_performance_local_v5_form_delivery_render_context(
                $GLOBALS['atlas_form_configuration_test']['payload']['form']
            ) === null,
        'disabled_configuration_keeps_public_form_inert'
    );

    $prior_payload_hash = atlas_performance_local_v5_page_payload_sha256(
        $GLOBALS['atlas_form_configuration_test']['payload']
    );
    $metadata_input = [
        'action' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION,
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD => 'valid-nonce',
        'atlas_command' => 'add_governed_customer_email',
        'expected_prior_sha256' => $prior_payload_hash,
    ];
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_request_is_authorized(
            $metadata_input
        ),
        'metadata_action_exact_post_authorized'
    );
    $reply_to_disabled_config = $candidate;
    $reply_to_disabled_config['reply_to'] = [
        'enabled' => false,
        'field_key' => null,
    ];
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $reply_to_disabled_config;
    $reply_to_disabled_state =
        atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state();
    $calls_before_reply_to_disabled = count(
        $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls']
    );
    ob_start();
    atlas_performance_local_v5_form_delivery_admin_render_page();
    $reply_to_disabled_html = (string) ob_get_clean();
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_configuration_errors(
            $reply_to_disabled_config,
            atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_candidate(
                $GLOBALS['atlas_form_configuration_test']['payload']
            )
        ) === []
            && $reply_to_disabled_state['configuration_ready_disabled'] === false
            && $reply_to_disabled_state['upgrade_available'] === false
            && !str_contains(
                $reply_to_disabled_html,
                'name="atlas_command" value="add_governed_customer_email"'
            )
            && atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
                $metadata_input
            ) === 'metadata_email_rejected'
            && count($GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'])
                === $calls_before_reply_to_disabled,
        'metadata_action_requires_reply_to_enabled_before_upgrade'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $candidate;
    $metadata_bad_hash = $metadata_input;
    $metadata_bad_hash['expected_prior_sha256'] = 'invalid';
    $metadata_extra = $metadata_input;
    $metadata_extra['payload'] = 'forbidden';
    atlas_form_configuration_test_check(
        !atlas_performance_local_v5_form_delivery_admin_request_is_authorized(
            $metadata_bad_hash
        )
            && !atlas_performance_local_v5_form_delivery_admin_request_is_authorized(
                $metadata_extra
            ),
        'metadata_action_hash_and_allowlist_are_exact'
    );
    $metadata_state =
        atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state();
    atlas_form_configuration_test_check(
        $metadata_state['metadata_valid'] === true
            && $metadata_state['metadata_sha256'] === $prior_payload_hash
            && $metadata_state['source_exact'] === true
            && $metadata_state['field_count'] === 5
            && $metadata_state['governed_email_present'] === false
            && $metadata_state['configuration_ready_disabled'] === true
            && $metadata_state['upgrade_available'] === true
            && is_string($metadata_state['target_sha256']),
        'metadata_action_server_rendered_state_is_exact'
    );
    ob_start();
    atlas_performance_local_v5_form_delivery_admin_render_page();
    $metadata_admin_html = (string) ob_get_clean();
    atlas_form_configuration_test_check(
        str_contains($metadata_admin_html, 'name="atlas_command" value="add_governed_customer_email"')
            && str_contains(
                $metadata_admin_html,
                'name="expected_prior_sha256" value="' . $prior_payload_hash . '"'
            )
            && str_contains($metadata_admin_html, 'Add governed Email field to Page 8')
            && !str_contains($metadata_admin_html, '<textarea')
            && !str_contains($metadata_admin_html, $private_recipient)
            && !str_contains($metadata_admin_html, $private_from),
        'metadata_action_renders_only_hidden_hash_and_redacted_state'
    );
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'] = [];
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_applied',
        'metadata_action_applied_and_readback_verified'
    );
    $metadata_call = $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'][0]
        ?? null;
    $metadata_body = is_array($metadata_call) ? ($metadata_call['body'] ?? null) : null;
    atlas_form_configuration_test_check(
        is_array($metadata_call)
            && $metadata_call['method'] === 'POST'
            && $metadata_call['route']
                === '/project-atlas/v4/performance-local-v5/page-payload/8'
            && $metadata_call['params'] === ['post_id' => '8']
            && atlas_performance_local_v5_form_delivery_exact_record(
                $metadata_body,
                [
                    'request_schema', 'expected_prior_sha256', 'website_id',
                    'planned_page_id', 'generated_page_id', 'wordpress_post_id',
                    'payload', 'request_identity',
                ]
            )
            && $metadata_body['expected_prior_sha256'] === $prior_payload_hash
            && count($metadata_body['payload']['form']['fields'] ?? []) === 6
            && ($metadata_body['payload']['form']['fields'][5] ?? null)
                === atlas_performance_local_v5_form_delivery_governed_email_field(),
        'metadata_action_invokes_existing_route_with_server_built_envelope'
    );
    $metadata_public_json = json_encode($metadata_body, JSON_THROW_ON_ERROR);
    atlas_form_configuration_test_check(
        !str_contains($metadata_public_json, $private_recipient)
            && !str_contains($metadata_public_json, $private_from)
            && !str_contains($metadata_public_json, 'smtp_password'),
        'metadata_action_envelope_contains_no_private_delivery_values'
    );
    $six_payload_hash = atlas_performance_local_v5_page_payload_sha256(
        $GLOBALS['atlas_form_configuration_test']['payload']
    );
    $six_metadata_input = $metadata_input;
    $six_metadata_input['expected_prior_sha256'] = $six_payload_hash;
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'unchanged';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $six_metadata_input
        ) === 'metadata_email_unchanged',
        'metadata_action_exact_six_field_repeat_is_unchanged'
    );
    $six_metadata_state =
        atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state();
    atlas_form_configuration_test_check(
        $six_metadata_state['metadata_valid'] === true
            && $six_metadata_state['metadata_sha256'] === $six_payload_hash
            && $six_metadata_state['field_count'] === 6
            && $six_metadata_state['governed_email_present'] === true
            && $six_metadata_state['configuration_ready_disabled'] === true
            && $six_metadata_state['upgrade_available'] === true
            && $six_metadata_state['target_sha256'] === $six_payload_hash,
        'metadata_action_exact_six_field_repeat_remains_available'
    );
    $GLOBALS['atlas_form_configuration_test']['payload'] =
        atlas_form_configuration_test_payload($five_fields);
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'applied';
    $GLOBALS['atlas_form_configuration_test']['page_payload_permission_mode'] = 'denied';
    $calls_before_permission_denied = count(
        $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls']
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_rejected'
            && count($GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'])
                === $calls_before_permission_denied,
        'metadata_action_permission_denied_before_callback'
    );
    $GLOBALS['atlas_form_configuration_test']['page_payload_permission_mode'] = 'allowed';
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'extra_response';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_verification_failed',
        'metadata_action_rejects_non_exact_route_response'
    );
    $GLOBALS['atlas_form_configuration_test']['payload'] =
        atlas_form_configuration_test_payload($five_fields);
    $stale_metadata_input = $metadata_input;
    $stale_metadata_input['expected_prior_sha256'] = str_repeat('0', 64);
    $calls_before_stale = count(
        $GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls']
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $stale_metadata_input
        ) === 'metadata_email_rejected'
            && count($GLOBALS['atlas_form_configuration_test']['page_payload_apply_calls'])
                === $calls_before_stale,
        'metadata_action_stale_prior_fails_before_route_call'
    );
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'no_readback';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_verification_failed',
        'metadata_action_requires_exact_readback'
    );
    $GLOBALS['atlas_form_configuration_test']['payload'] =
        atlas_form_configuration_test_payload($five_fields);
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'error';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_rejected',
        'metadata_action_route_error_fails_closed'
    );
    $GLOBALS['atlas_form_configuration_test']['payload'] =
        atlas_form_configuration_test_payload($five_fields);
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'config_race';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
            $metadata_input
        ) === 'metadata_email_verification_failed',
        'metadata_action_rechecks_disabled_configuration_after_callback'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $candidate;
    $GLOBALS['atlas_form_configuration_test']['page_payload_apply_mode'] = 'applied';
    $GLOBALS['atlas_form_configuration_test']['payload'] =
        atlas_form_configuration_test_payload($five_fields);

    $invalid_six_fields = $five_fields;
    $invalid_email_field = atlas_performance_local_v5_form_delivery_governed_email_field();
    $invalid_email_field['label'] = 'Alternate email';
    $invalid_six_fields[] = $invalid_email_field;
    $GLOBALS['atlas_form_configuration_test']['payload'] = atlas_form_configuration_test_payload(
        $invalid_six_fields
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_candidate($input) === null,
        'invalid_optional_sixth_field_structure_rejected'
    );
    $six_fields = $five_fields;
    $six_fields[] = atlas_performance_local_v5_form_delivery_governed_email_field();
    $GLOBALS['atlas_form_configuration_test']['payload'] = atlas_form_configuration_test_payload(
        $six_fields
    );
    $enabled = atlas_performance_local_v5_form_delivery_admin_enable_candidate();
    atlas_form_configuration_test_check(
        is_array($enabled)
            && $enabled['enabled'] === true
            && atlas_performance_local_v5_form_delivery_configuration_errors(
                $enabled,
                $GLOBALS['atlas_form_configuration_test']['payload']
            ) === [],
        'exact_valid_option_can_enable'
    );
    $invalid_binding = $enabled;
    $invalid_binding['optional_sixth_field']['definition_hash'] = str_repeat('0', 64);
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_configuration_errors(
            $invalid_binding,
            $GLOBALS['atlas_form_configuration_test']['payload']
        ) !== [],
        'invalid_optional_sixth_field_binding_rejected'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $enabled;
    $disabled = atlas_performance_local_v5_form_delivery_admin_disable_candidate();
    $expected_disabled = $enabled;
    $expected_disabled['enabled'] = false;
    atlas_form_configuration_test_check(
        $disabled === $expected_disabled,
        'disable_preserves_configuration_exactly'
    );
    $alternate_field = [
        'field_key' => 'alternate',
        'label' => 'Alternate',
        'required' => false,
        'control' => 'input',
        'input_type' => 'text',
        'order' => 6,
        'maximum_length' => 100,
        'validation' => [
            'rule' => 'nonempty_text',
            'minimum_length' => 1,
            'maximum_length' => 100,
        ],
    ];
    $alternate_fields = $five_fields;
    $alternate_fields[] = $alternate_field;
    $alternate_payload = atlas_form_configuration_test_payload($alternate_fields);
    $alternate_config = $enabled;
    $alternate_config['field_definition_hash'] =
        atlas_performance_local_v5_form_delivery_hash_fields($alternate_fields);
    $alternate_config['optional_sixth_field'] = [
        'field_key' => 'alternate',
        'input_type' => 'text',
        'definition_hash' => atlas_performance_local_v5_form_delivery_hash_sixth(
            $alternate_field
        ),
    ];
    $alternate_config['reply_to'] = ['enabled' => false, 'field_key' => null];
    $GLOBALS['atlas_form_configuration_test']['payload'] = $alternate_payload;
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $alternate_config;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_configuration_errors(
            $alternate_config,
            $alternate_payload
        ) === []
            && atlas_performance_local_v5_form_delivery_config_for_payload(
                $alternate_payload
            ) === null,
        'self_consistent_non_governed_sixth_field_fails_closed'
    );
    $GLOBALS['atlas_form_configuration_test']['payload'] = atlas_form_configuration_test_payload(
        $six_fields
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $enabled;

    $status = atlas_performance_local_v5_form_delivery_admin_redacted_status();
    $expected_status_keys = [
        'configured', 'enabled', 'schema_valid', 'field_definition_hash_match',
        'recipient_present', 'from_present', 'from_domain_valid', 'reply_to_mode',
        'optional_sixth_field_mode',
    ];
    atlas_form_configuration_test_check(
        array_keys($status) === $expected_status_keys
            && $status['configured'] === true
            && $status['schema_valid'] === true
            && $status['field_definition_hash_match'] === true
            && $status['recipient_present'] === true
            && $status['from_present'] === true
            && $status['from_domain_valid'] === true
            && $status['reply_to_mode'] === 'enabled'
            && $status['optional_sixth_field_mode'] === 'enabled',
        'saved_status_is_exact_and_redacted'
    );
    $status_json = json_encode($status, JSON_THROW_ON_ERROR);
    atlas_form_configuration_test_check(
        !str_contains($status_json, $private_recipient)
            && !str_contains($status_json, $private_from),
        'redacted_status_contains_no_private_values'
    );

    ob_start();
    atlas_performance_local_v5_form_delivery_admin_render_page();
    $admin_html = (string) ob_get_clean();
    atlas_form_configuration_test_check(
        !str_contains($admin_html, $private_recipient)
            && !str_contains($admin_html, $private_from)
            && !str_contains($admin_html, '_wp_http_referer')
            && !str_contains($admin_html, 'name="submit"'),
        'admin_html_is_private_and_has_no_extra_post_controls'
    );
    preg_match_all('/<form\b[^>]*>(.*?)<\/form>/s', $admin_html, $form_matches);
    atlas_form_configuration_test_check(
        count($form_matches[1] ?? []) === 4,
        'four_admin_forms_rendered'
    );
    $expected_form_keys = [
        [
            'action', 'atlas_command', ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,
            'recipient_email', 'from_name', 'from_email', 'subject_template',
            'success_message', 'failure_message', 'optional_sixth_field_mode',
            'reply_to_mode',
        ],
        ['action', 'atlas_command', ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD],
        ['action', 'atlas_command', ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD],
        ['action', 'atlas_command', ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD],
    ];
    foreach ($form_matches[1] as $index => $form_html) {
        preg_match_all('/\bname="([^"]+)"/', $form_html, $name_matches);
        $actual_names = array_values(array_unique($name_matches[1] ?? []));
        sort($actual_names, SORT_STRING);
        $expected_names = $expected_form_keys[$index];
        sort($expected_names, SORT_STRING);
        atlas_form_configuration_test_check(
            $actual_names === $expected_names,
            'rendered_form_control_keys_' . (string) ($index + 1)
        );
    }

    $prior = $candidate;
    $replacement = $candidate;
    $replacement['success_message'] = 'A different synthetic message.';
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $prior;
    $GLOBALS['atlas_form_configuration_test']['corrupt_next_update'] = true;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_write_verified($replacement)
            === 'write_failed_prior_restored'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION) === $prior,
        'failed_readback_restores_exact_prior_option'
    );
    unset($GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ]);
    $GLOBALS['atlas_form_configuration_test']['corrupt_next_update'] = true;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_write_verified($candidate)
            === 'write_failed_prior_restored'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null) === null,
        'failed_initial_readback_restores_option_absence'
    );
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_write_verified($candidate) === 'saved'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION) === $candidate,
        'successful_write_has_exact_readback'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $enabled;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
            === 'rejected'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION) === $enabled,
        'enabled_configuration_cannot_be_removed'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $candidate;
    $GLOBALS['atlas_form_configuration_test']['delete_mode'] = 'retain_prior';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
            === 'remove_failed_prior_restored'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION) === $candidate,
        'failed_removal_with_prior_readback_preserves_prior'
    );
    $GLOBALS['atlas_form_configuration_test']['delete_mode'] = 'corrupt_residual';
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
            === 'remove_failed_prior_restored'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION) === $candidate,
        'corrupt_removal_residual_restores_exact_prior'
    );
    $GLOBALS['atlas_form_configuration_test']['delete_mode'] = 'corrupt_residual';
    $GLOBALS['atlas_form_configuration_test']['corrupt_next_update'] = true;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
            === 'remove_failed_rollback_failed',
        'corrupt_removal_and_restore_failure_is_explicit'
    );
    $GLOBALS['atlas_form_configuration_test']['options'][
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
    ] = $candidate;
    atlas_form_configuration_test_check(
        atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
            === 'removed'
            && get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null) === null,
        'disabled_configuration_removal_restores_exact_absence'
    );
    foreach ($GLOBALS['atlas_form_configuration_test']['option_writes'] as $write) {
        atlas_form_configuration_test_check(
            $write[1] === ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION,
            'only_governed_option_written'
        );
    }

    $safe_response = atlas_performance_local_v5_form_delivery_safe_response(
        'success',
        $candidate['success_message'],
        200
    );
    $public_json = json_encode($safe_response->get_data(), JSON_THROW_ON_ERROR);
    atlas_form_configuration_test_check(
        $safe_response->get_status() === 200
            && !str_contains($public_json, $private_recipient)
            && !str_contains($public_json, $private_from),
        'public_response_contains_no_private_values'
    );

    $GLOBALS['atlas_form_configuration_test']['environment'] = 'production';
    atlas_performance_local_v5_form_delivery_admin_register_page();
    atlas_form_configuration_test_check(
        $GLOBALS['atlas_form_configuration_test']['admin_pages'] === []
            && !atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input),
        'production_blocks_admin_page_and_post_authorization'
    );
    $GLOBALS['atlas_form_configuration_test']['environment'] = 'staging';
    atlas_performance_local_v5_form_delivery_admin_register_page();
    atlas_form_configuration_test_check(
        $GLOBALS['atlas_form_configuration_test']['admin_pages'] === [[
            'page_title' => 'Performance Local V5 Form Delivery',
            'menu_title' => 'V5 Form Delivery',
            'capability' => 'manage_options',
            'menu_slug' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_PAGE,
            'callback' => 'atlas_performance_local_v5_form_delivery_admin_render_page',
        ]],
        'private_admin_page_registration_exact'
    );

    $result = [
        'status' => 'PASS',
        'version' => '0.57.16',
        'check_count' => count($GLOBALS['atlas_form_configuration_test']['checks']),
        'private_values_redacted' => true,
    ];
    $encoded = json_encode($result, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    atlas_form_configuration_test_check(
        !str_contains($encoded, $private_recipient) && !str_contains($encoded, $private_from),
        'sanitized_result_has_no_private_values'
    );
    $result['check_count'] = count($GLOBALS['atlas_form_configuration_test']['checks']);
    echo json_encode($result, JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
    exit(0);
} catch (Atlas_Form_Configuration_Test_Failure $error) {
    fwrite(STDERR, json_encode([
        'status' => 'FAIL',
        'failed_check' => $error->getMessage(),
    ], JSON_UNESCAPED_SLASHES) . "\n");
    exit(1);
} catch (Throwable $error) {
    fwrite(STDERR, json_encode([
        'status' => 'FAIL',
        'failed_check' => 'internal_harness_error',
        'exception' => get_class($error),
    ], JSON_UNESCAPED_SLASHES) . "\n");
    exit(1);
}
