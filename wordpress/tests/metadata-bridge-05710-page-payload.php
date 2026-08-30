<?php
/**
 * Process-isolated regression harness for the Metadata Bridge 0.57.10
 * private Performance Local V5 page-payload route.
 *
 * Usage:
 *   php metadata-bridge-05710-page-payload.php <case> <payloads.json>
 */

declare(strict_types=1);

$atlas_case = $argv[1] ?? '';
$atlas_payload_path = $argv[2] ?? '';
$atlas_environment_cases = [
    'local', 'staging', 'development', 'production', 'unset', 'invalid', 'unavailable',
];
$atlas_supported_cases = array_merge(['contract'], $atlas_environment_cases);
if (!in_array($atlas_case, $atlas_supported_cases, true)) {
    fwrite(STDERR, "unsupported case\n");
    exit(2);
}

define('ABSPATH', __DIR__ . '/');
define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.10');

$GLOBALS['atlas_route_test'] = [
    'environment' => $atlas_case === 'contract' ? 'staging' : match ($atlas_case) {
        'unset' => '',
        'invalid' => 'not-a-wordpress-environment',
        default => $atlas_case,
    },
    'logged_in' => true,
    'manage_options' => true,
    'edit_post' => true,
    'actions' => [],
    'filters' => [],
    'routes' => [],
    'adds' => [],
    'updates' => [],
    'rollback_updates' => [],
    'deletes' => [],
    'force_corrupt_readback' => false,
    'arm_corrupt_after_update' => false,
    'arm_concurrent_before_add' => false,
    'arm_concurrent_before_update' => false,
    'arm_concurrent_before_delete' => false,
    'arm_successor_after_update' => false,
    'arm_false_after_delete' => false,
    'concurrent_value' => null,
    'checks' => [],
    'meta' => [
        8 => [
            '_wp_page_template' => 'theme-owned-page-template.php',
        ],
    ],
    'posts' => [],
    'options' => [
        'home' => 'https://staging.example.test',
        'siteurl' => 'https://staging.example.test',
        'blog_public' => '0',
        '_project_atlas_estimate_form_delivery_v1' => [
            'recipient_email' => 'private-recipient@delivery.example.test',
            'from_email' => 'no-reply@delivery.example.test',
        ],
    ],
];

if ($atlas_case !== 'unavailable') {
    function wp_get_environment_type(): string {
        return (string) $GLOBALS['atlas_route_test']['environment'];
    }
}

class WP_Error {
    private string $code;
    private string $message;
    private array $data;

    public function __construct(string $code = '', string $message = '', array $data = []) {
        $this->code = $code;
        $this->message = $message;
        $this->data = $data;
    }

    public function get_error_code(): string { return $this->code; }
    public function get_error_message(): string { return $this->message; }
    public function get_error_data(): array { return $this->data; }
}

class WP_Post {
    public int $ID;
    public string $post_type;
    public string $post_status;
    public string $post_title;
    public string $post_name;
    public string $post_content;
    public string $post_excerpt;
    public int $post_author;
    public int $post_parent;
    public int $menu_order;

    public function __construct(int $id, string $type = 'page') {
        $this->ID = $id;
        $this->post_type = $type;
        $this->post_status = 'publish';
        $this->post_title = $id === 8
            ? 'Drywood Termite Tenting in Orlando, FL'
            : 'Unrelated record';
        $this->post_name = $id === 8
            ? 'drywood-termite-tenting-orlando-fl'
            : 'unrelated-record';
        $this->post_content = '<!-- governed WordPress content remains untouched -->';
        $this->post_excerpt = 'Existing excerpt';
        $this->post_author = 7;
        $this->post_parent = 0;
        $this->menu_order = 3;
    }
}

class WP_REST_Request {
    private array $params;
    private array $json;
    private string $body;
    private array $headers;

    public function __construct(array $params, array $json = [], ?string $body = null, array $headers = []) {
        $this->params = $params;
        $this->json = $json;
        $encoded = json_encode($json, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
        $this->body = $body ?? (is_string($encoded) ? $encoded : '');
        $this->headers = array_change_key_case($headers, CASE_LOWER);
    }

    public function get_param(string $key) { return $this->params[$key] ?? null; }
    public function get_json_params(): array { return $this->json; }
    public function get_body(): string { return $this->body; }
    public function get_header(string $key): string {
        return (string) ($this->headers[strtolower($key)] ?? '');
    }
}

class WP_REST_Response {
    private array $data;
    private int $status;

    public function __construct(array $data, int $status = 200) {
        $this->data = $data;
        $this->status = $status;
    }

    public function get_data(): array { return $this->data; }
    public function get_status(): int { return $this->status; }
}

$GLOBALS['atlas_route_test']['posts'][8] = new WP_Post(8, 'page');
$GLOBALS['atlas_route_test']['posts'][9] = new WP_Post(9, 'post');

function atlas_route_test_check(bool $condition, string $identity): void {
    if (!$condition) { throw new RuntimeException($identity); }
    $GLOBALS['atlas_route_test']['checks'][] = $identity;
}

function atlas_route_test_response_data($response): array {
    atlas_route_test_check($response instanceof WP_REST_Response, 'response_is_rest_response');
    return $response->get_data();
}

function atlas_route_test_error($value, string $code, int $status): void {
    atlas_route_test_check($value instanceof WP_Error, $code . '_is_error');
    atlas_route_test_check($value->get_error_code() === $code, $code . '_code');
    atlas_route_test_check(($value->get_error_data()['status'] ?? null) === $status, $code . '_status');
}

function atlas_route_test_no_raw_payload(array $response, array $payload): void {
    $encoded = json_encode($response, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
    atlas_route_test_check(is_string($encoded), 'response_encodes');
    atlas_route_test_check(!str_contains($encoded, (string) $payload['hero']['introduction']), 'response_has_no_payload_copy');
    atlas_route_test_check(!str_contains($encoded, 'private-recipient@delivery.example.test'), 'response_has_no_private_recipient');
    atlas_route_test_check(!str_contains($encoded, 'no-reply@delivery.example.test'), 'response_has_no_private_from');
}

function add_action(string $hook, $callback, int $priority = 10, int $accepted_args = 1): bool {
    $GLOBALS['atlas_route_test']['actions'][] = compact('hook', 'callback', 'priority', 'accepted_args');
    return true;
}

function add_filter(string $hook, $callback, int $priority = 10, int $accepted_args = 1): bool {
    $GLOBALS['atlas_route_test']['filters'][] = compact('hook', 'callback', 'priority', 'accepted_args');
    return true;
}

function register_rest_route(string $namespace, string $route, array $args, bool $override = false): bool {
    $GLOBALS['atlas_route_test']['routes'][] = compact('namespace', 'route', 'args', 'override');
    return true;
}

function wp_json_encode($value, int $flags = 0) {
    return json_encode($value, $flags);
}

function is_wp_error($value): bool { return $value instanceof WP_Error; }
function is_user_logged_in(): bool { return (bool) $GLOBALS['atlas_route_test']['logged_in']; }

function current_user_can(string $capability, ...$args): bool {
    if ($capability === 'manage_options') { return (bool) $GLOBALS['atlas_route_test']['manage_options']; }
    if ($capability === 'edit_post') { return (bool) $GLOBALS['atlas_route_test']['edit_post']; }
    if ($capability === 'edit_pages') { return true; }
    return false;
}

function get_post(int $post_id): ?WP_Post {
    return $GLOBALS['atlas_route_test']['posts'][$post_id] ?? null;
}

function metadata_exists(string $type, int $post_id, string $meta_key): bool {
    return $type === 'post'
        && array_key_exists($meta_key, $GLOBALS['atlas_route_test']['meta'][$post_id] ?? []);
}

function get_post_meta(int $post_id, string $meta_key, bool $single = true) {
    if ($meta_key === '_project_atlas_performance_local_v5_v1'
        && $GLOBALS['atlas_route_test']['force_corrupt_readback']) {
        $GLOBALS['atlas_route_test']['force_corrupt_readback'] = false;
        return ['forced' => 'readback-verification-failure'];
    }
    return $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] ?? '';
}

function add_post_meta(int $post_id, string $meta_key, $value, bool $unique = false) {
    $GLOBALS['atlas_route_test']['adds'][] = compact('post_id', 'meta_key', 'value', 'unique');
    if ($GLOBALS['atlas_route_test']['arm_concurrent_before_add']) {
        $GLOBALS['atlas_route_test']['arm_concurrent_before_add'] = false;
        $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key]
            = $GLOBALS['atlas_route_test']['concurrent_value'];
        return false;
    }
    if ($unique && array_key_exists($meta_key, $GLOBALS['atlas_route_test']['meta'][$post_id] ?? [])) {
        return false;
    }
    $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] = $value;
    return 101;
}

function update_post_meta(int $post_id, string $meta_key, $value, $prev_value = '') {
    $GLOBALS['atlas_route_test']['updates'][] = compact('post_id', 'meta_key', 'value', 'prev_value');
    if ($GLOBALS['atlas_route_test']['arm_concurrent_before_update']) {
        $GLOBALS['atlas_route_test']['arm_concurrent_before_update'] = false;
        $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key]
            = $GLOBALS['atlas_route_test']['concurrent_value'];
        return false;
    }
    if (!array_key_exists($meta_key, $GLOBALS['atlas_route_test']['meta'][$post_id] ?? [])
        || ($prev_value !== ''
            && $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] !== $prev_value)) {
        return false;
    }
    $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] = $value;
    if ($GLOBALS['atlas_route_test']['arm_corrupt_after_update']) {
        $GLOBALS['atlas_route_test']['arm_corrupt_after_update'] = false;
        $GLOBALS['atlas_route_test']['force_corrupt_readback'] = true;
    }
    if ($GLOBALS['atlas_route_test']['arm_successor_after_update']) {
        $GLOBALS['atlas_route_test']['arm_successor_after_update'] = false;
        $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key]
            = $GLOBALS['atlas_route_test']['concurrent_value'];
    }
    return true;
}

function update_metadata(string $type, int $post_id, string $meta_key, $value, $prev_value = '') {
    $GLOBALS['atlas_route_test']['rollback_updates'][]
        = compact('type', 'post_id', 'meta_key', 'value', 'prev_value');
    if (!array_key_exists($meta_key, $GLOBALS['atlas_route_test']['meta'][$post_id] ?? [])
        || ($prev_value !== ''
            && $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] !== $prev_value)) {
        return false;
    }
    $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] = $value;
    return true;
}

function delete_post_meta(int $post_id, string $meta_key, $meta_value = ''): bool {
    $GLOBALS['atlas_route_test']['deletes'][] = compact('post_id', 'meta_key', 'meta_value');
    if ($GLOBALS['atlas_route_test']['arm_concurrent_before_delete']) {
        $GLOBALS['atlas_route_test']['arm_concurrent_before_delete'] = false;
        $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key]
            = $GLOBALS['atlas_route_test']['concurrent_value'];
        return false;
    }
    if (!array_key_exists($meta_key, $GLOBALS['atlas_route_test']['meta'][$post_id] ?? [])) { return false; }
    if ($meta_value !== '' && $GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key] !== $meta_value) {
        return false;
    }
    unset($GLOBALS['atlas_route_test']['meta'][$post_id][$meta_key]);
    if ($GLOBALS['atlas_route_test']['arm_false_after_delete']) {
        $GLOBALS['atlas_route_test']['arm_false_after_delete'] = false;
        return false;
    }
    return true;
}

function get_option(string $name, $default = false) {
    return $GLOBALS['atlas_route_test']['options'][$name] ?? $default;
}

function esc_url_raw(string $value): string { return $value; }
function wp_strip_all_tags(string $value): string { return strip_tags($value); }
function get_post_thumbnail_id(int $post_id): int { return $post_id === 8 ? 31 : 0; }
function rest_ensure_response(array $value): WP_REST_Response { return new WP_REST_Response($value, 200); }

function atlas_route_test_request(int $post_id, array $body = [], ?string $raw = null): WP_REST_Request {
    return new WP_REST_Request(['post_id' => (string) $post_id], $body, $raw);
}

function atlas_route_test_post_body(array $payload, ?string $prior = null): array {
    return [
        'request_schema' => 'project-atlas-performance-local-v5-page-payload-request@1',
        'expected_prior_sha256' => $prior,
        'website_id' => 1,
        'planned_page_id' => 41,
        'generated_page_id' => 41,
        'wordpress_post_id' => 8,
        'payload' => $payload,
        'request_identity' => '123e4567-e89b-42d3-a456-426614174000',
    ];
}

function atlas_route_test_delete_body(?string $current): array {
    return [
        'request_schema' => 'project-atlas-performance-local-v5-page-payload-delete@1',
        'expected_current_sha256' => $current,
        'wordpress_post_id' => 8,
        'request_identity' => '123e4567-e89b-42d3-a456-426614174001',
    ];
}

try {
    atlas_route_test_check(is_file($atlas_payload_path), 'payload_fixture_exists');
    $atlas_payloads = json_decode((string) file_get_contents($atlas_payload_path), true, 512, JSON_THROW_ON_ERROR);
    $atlas_matches = array_values(array_filter(
        $atlas_payloads,
        static fn($value): bool => is_array($value)
            && ($value['payload_identity']['fixture_key'] ?? null) === 'city_service'
    ));
    atlas_route_test_check(count($atlas_matches) === 1, 'one_city_service_payload');
    $atlas_payload = $atlas_matches[0];
    $atlas_planned_inputs = array_values(array_filter(
        $atlas_payload['payload_identity']['frozen_inputs'] ?? [],
        static fn($value): bool => is_array($value)
            && is_string($value['path'] ?? null)
            && preg_match('#^atlas/planned-page/[1-9][0-9]*$#D', $value['path']) === 1
    ));
    if ($atlas_planned_inputs === []) {
        // Older renderer-only fixtures predate the private transport envelope.
        // Upgrade only the disposable harness value; actual builder output must
        // already carry its governed Planned Page binding.
        $atlas_payload['payload_identity']['frozen_inputs'][] = [
            'path' => 'atlas/planned-page/41',
            'sha256' => hash('sha256', 'disposable-planned-page-41'),
        ];
        $atlas_planned_inputs = [
            $atlas_payload['payload_identity']['frozen_inputs'][
                array_key_last($atlas_payload['payload_identity']['frozen_inputs'])
            ],
        ];
    }
    atlas_route_test_check(
        count($atlas_planned_inputs) === 1
            && $atlas_planned_inputs[0]['path'] === 'atlas/planned-page/41',
        'one_exact_planned_page_frozen_input'
    );
    // The route is page-generic. Bind the disposable WordPress target to the
    // exact governed title/slug in whichever valid payload fixture is supplied.
    $GLOBALS['atlas_route_test']['posts'][8]->post_title = (string) ($atlas_payload['page']['title'] ?? '');
    $GLOBALS['atlas_route_test']['posts'][8]->post_name = (string) ($atlas_payload['page']['slug'] ?? '');

    $atlas_package = dirname(__DIR__) . '/project-atlas-metadata-bridge-0.57.10';
    require_once $atlas_package . '/includes/performance-local-v5-renderer.php';
    require_once $atlas_package . '/includes/performance-local-v5-page-payload.php';

    atlas_performance_local_v5_page_payload_register_route();
    atlas_route_test_check(count($GLOBALS['atlas_route_test']['routes']) === 1, 'one_route_family');
    $atlas_route = $GLOBALS['atlas_route_test']['routes'][0];
    atlas_route_test_check($atlas_route['namespace'] === 'project-atlas/v4', 'route_namespace');
    atlas_route_test_check(
        $atlas_route['route'] === '/performance-local-v5/page-payload/(?P<post_id>\d+)',
        'route_pattern'
    );
    atlas_route_test_check(
        array_column($atlas_route['args'], 'methods') === ['GET', 'POST', 'DELETE'],
        'route_methods'
    );

    $atlas_allowed = in_array($atlas_case, ['contract', 'local', 'staging'], true);
    $atlas_permission = atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(8));
    if (!$atlas_allowed) {
        atlas_route_test_error($atlas_permission, 'atlas_v5_page_payload_environment_denied', 403);
        echo json_encode([
            'case' => $atlas_case,
            'allowed' => false,
            'checks' => count($GLOBALS['atlas_route_test']['checks']),
        ], JSON_UNESCAPED_SLASHES) . "\n";
        exit(0);
    }
    atlas_route_test_check($atlas_permission === true, 'allowed_permission');

    if ($atlas_case !== 'contract') {
        echo json_encode([
            'case' => $atlas_case,
            'allowed' => true,
            'checks' => count($GLOBALS['atlas_route_test']['checks']),
        ], JSON_UNESCAPED_SLASHES) . "\n";
        exit(0);
    }

    $atlas_known = ['z' => '/slash/✓', 'a' => ['b' => 2, 'a' => 1], 'list' => [2, 1]];
    $atlas_reordered = ['list' => [2, 1], 'a' => ['a' => 1, 'b' => 2], 'z' => '/slash/✓'];
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_sha256($atlas_known)
            === 'c320206791c7df78901ffd563080b5a526e362ac1c6139a9ade6b0d2fb939fa8',
        'canonical_hash_known_vector'
    );
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_sha256($atlas_known)
            === atlas_performance_local_v5_page_payload_sha256($atlas_reordered),
        'canonical_hash_sorts_records'
    );
    $atlas_list_changed = $atlas_known;
    $atlas_list_changed['list'] = [1, 2];
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_sha256($atlas_known)
            !== atlas_performance_local_v5_page_payload_sha256($atlas_list_changed),
        'canonical_hash_preserves_list_order'
    );
    $atlas_cross_runtime_vector = [
        'whole' => 16.0,
        'zero' => 0.0,
        'negative_zero' => -0.0,
        'fraction' => 0.5,
        'small_exponent' => 1e-7,
        'large_exponent' => 1e20,
        'line_separators' => "before\u{2028}between\u{2029}after",
    ];
    $atlas_cross_runtime_json =
        '{"fraction":0.5,"large_exponent":1.0e+20,'
        . '"line_separators":"before' . "\u{2028}" . 'between' . "\u{2029}" . 'after",'
        . '"negative_zero":-0.0,"small_exponent":1.0e-7,'
        . '"whole":16.0,"zero":0.0}';
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_json($atlas_cross_runtime_vector)
            === $atlas_cross_runtime_json,
        'canonical_json_matches_python_line_separator_and_float_vector'
    );
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_sha256($atlas_cross_runtime_vector)
            === 'b0ef0698db793640caf91ed603fdee9ab7b288cd3e71e30acc65a0988d60f276',
        'canonical_hash_cross_runtime_vector'
    );
    foreach ([NAN, INF, -INF] as $atlas_non_finite) {
        atlas_route_test_check(
            atlas_performance_local_v5_page_payload_json(['value' => $atlas_non_finite]) === null,
            'canonical_json_rejects_non_finite_' . count($GLOBALS['atlas_route_test']['checks'])
        );
    }

    $GLOBALS['atlas_route_test']['logged_in'] = false;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(8)),
        'atlas_v5_page_payload_authentication_required',
        401
    );
    $GLOBALS['atlas_route_test']['logged_in'] = true;
    $GLOBALS['atlas_route_test']['manage_options'] = false;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(8)),
        'atlas_v5_page_payload_manage_options_required',
        403
    );
    $GLOBALS['atlas_route_test']['manage_options'] = true;
    $GLOBALS['atlas_route_test']['edit_post'] = false;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(8)),
        'atlas_v5_page_payload_edit_post_required',
        403
    );
    $GLOBALS['atlas_route_test']['edit_post'] = true;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(404)),
        'atlas_v5_page_payload_post_not_found',
        404
    );
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_permission(atlas_route_test_request(9)),
        'atlas_v5_page_payload_wrong_post_type',
        409
    );

    $atlas_before_post = clone $GLOBALS['atlas_route_test']['posts'][8];
    $atlas_before_template = $GLOBALS['atlas_route_test']['meta'][8]['_wp_page_template'];
    $atlas_inspection = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_inspect(atlas_route_test_request(8))
    );
    atlas_route_test_check(array_keys($atlas_inspection) === [
        'route_schema', 'metadata_bridge_version', 'environment_type', 'home', 'siteurl',
        'blog_public', 'post_id', 'post_type', 'post_status', 'post_title', 'post_slug',
        'metadata_exists', 'metadata_sha256', 'metadata_valid', 'atlas_identity',
    ], 'inspection_exact_keys');
    atlas_route_test_check(!$atlas_inspection['metadata_exists'], 'inspection_absent');
    atlas_route_test_check($atlas_inspection['metadata_sha256'] === null, 'inspection_absent_hash');
    atlas_route_test_check($atlas_inspection['blog_public'] === 0, 'inspection_search_discouraged');
    atlas_route_test_no_raw_payload($atlas_inspection, $atlas_payload);

    $atlas_private_payload = $atlas_payload;
    $atlas_private_payload['hero']['introduction'] .= ' private-recipient@delivery.example.test';
    atlas_route_test_check(
        atlas_performance_local_v5_validate_payload($atlas_private_payload) === [],
        'private_delivery_candidate_is_structurally_valid'
    );
    $atlas_private_error = atlas_performance_local_v5_page_payload_apply(
        atlas_route_test_request(8, atlas_route_test_post_body($atlas_private_payload))
    );
    atlas_route_test_error(
        $atlas_private_error,
        'atlas_v5_page_payload_private_delivery_value',
        422
    );
    atlas_route_test_check(
        !str_contains(
            json_encode([
                $atlas_private_error->get_error_message(),
                $atlas_private_error->get_error_data(),
            ], JSON_UNESCAPED_SLASHES),
            'private-recipient@delivery.example.test'
        ),
        'private_delivery_rejection_is_sanitized'
    );

    foreach ([
        'post_title' => 'Changed title',
        'post_name' => 'changed-slug',
        'post_status' => 'draft',
    ] as $atlas_field => $atlas_changed_value) {
        $atlas_original_value = $GLOBALS['atlas_route_test']['posts'][8]->{$atlas_field};
        $GLOBALS['atlas_route_test']['posts'][8]->{$atlas_field} = $atlas_changed_value;
        atlas_route_test_error(
            atlas_performance_local_v5_page_payload_apply(
                atlas_route_test_request(8, atlas_route_test_post_body($atlas_payload))
            ),
            'atlas_v5_page_payload_target_identity_changed',
            409
        );
        $GLOBALS['atlas_route_test']['posts'][8]->{$atlas_field} = $atlas_original_value;
    }
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 0
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'private_and_target_identity_failures_are_write_free'
    );

    $atlas_add_race_payload = $atlas_payload;
    $atlas_add_race_payload['page']['meta_description'] .= ' Concurrent successor.';
    atlas_route_test_check(
        atlas_performance_local_v5_validate_payload($atlas_add_race_payload) === [],
        'add_race_successor_is_valid'
    );
    $GLOBALS['atlas_route_test']['concurrent_value'] = $atlas_add_race_payload;
    $GLOBALS['atlas_route_test']['arm_concurrent_before_add'] = true;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(
            atlas_route_test_request(8, atlas_route_test_post_body($atlas_payload))
        ),
        'atlas_v5_page_payload_stale_prior_state',
        409
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
            === $atlas_add_race_payload,
        'add_race_preserves_concurrent_successor'
    );
    unset($GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']);
    $GLOBALS['atlas_route_test']['adds'] = [];

    $atlas_apply_body = atlas_route_test_post_body($atlas_payload);
    $atlas_applied = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_apply_body))
    );
    $atlas_payload_hash = atlas_performance_local_v5_page_payload_sha256($atlas_payload);
    atlas_route_test_check($atlas_applied['status'] === 'APPLIED', 'apply_status');
    atlas_route_test_check($atlas_applied['prior_sha256'] === null, 'apply_prior_absent');
    atlas_route_test_check($atlas_applied['resulting_sha256'] === $atlas_payload_hash, 'apply_hash');
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'apply_one_forward_add'
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['adds'][0]['meta_key'] === '_project_atlas_performance_local_v5_v1'
            && $GLOBALS['atlas_route_test']['adds'][0]['unique'] === true,
        'apply_only_v5_key'
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['posts'][8] == $atlas_before_post,
        'apply_post_fields_unchanged'
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_wp_page_template'] === $atlas_before_template,
        'apply_editor_template_unchanged'
    );
    atlas_route_test_no_raw_payload($atlas_applied, $atlas_payload);

    $atlas_present = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_inspect(atlas_route_test_request(8))
    );
    atlas_route_test_check($atlas_present['metadata_exists'], 'inspection_present');
    atlas_route_test_check($atlas_present['metadata_valid'], 'inspection_valid');
    atlas_route_test_check($atlas_present['metadata_sha256'] === $atlas_payload_hash, 'inspection_hash');
    atlas_route_test_check($atlas_present['atlas_identity'] === [
        'website_id' => 1,
        'generated_page_id' => 41,
        'source_composition' => $atlas_payload['payload_identity']['source_composition'],
        'source_sha256' => $atlas_payload['payload_identity']['source_hash'],
    ], 'inspection_atlas_identity');
    atlas_route_test_no_raw_payload($atlas_present, $atlas_payload);

    $atlas_lost_response_replay = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_apply(
            atlas_route_test_request(8, atlas_route_test_post_body($atlas_payload, null))
        )
    );
    atlas_route_test_check(
        $atlas_lost_response_replay['status'] === 'UNCHANGED',
        'apply_original_request_after_lost_response_is_unchanged'
    );
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'lost_response_replay_zero_writes'
    );
    $atlas_exact_retry_original_title = $GLOBALS['atlas_route_test']['posts'][8]->post_title;
    $GLOBALS['atlas_route_test']['posts'][8]->post_title = 'Changed after response loss';
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(
            atlas_route_test_request(8, atlas_route_test_post_body($atlas_payload, null))
        ),
        'atlas_v5_page_payload_target_identity_changed',
        409
    );
    $GLOBALS['atlas_route_test']['posts'][8]->post_title = $atlas_exact_retry_original_title;
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'lost_response_replay_target_drift_is_write_free'
    );

    $atlas_unchanged_body = atlas_route_test_post_body($atlas_payload, $atlas_payload_hash);
    $atlas_unchanged = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_unchanged_body))
    );
    atlas_route_test_check($atlas_unchanged['status'] === 'UNCHANGED', 'apply_unchanged_status');
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'unchanged_zero_writes'
    );

    $atlas_stale_payload = $atlas_payload;
    $atlas_stale_payload['page']['meta_description'] .= ' Stale candidate.';
    atlas_route_test_check(
        atlas_performance_local_v5_validate_payload($atlas_stale_payload) === [],
        'stale_candidate_payload_is_valid'
    );
    $atlas_stale = atlas_route_test_post_body($atlas_stale_payload, str_repeat('0', 64));
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_stale)),
        'atlas_v5_page_payload_stale_prior_state',
        409
    );
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'stale_zero_writes'
    );

    $atlas_unknown = $atlas_unchanged_body;
    $atlas_unknown['unknown'] = 'denied';
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_unknown)),
        'atlas_v5_page_payload_invalid_envelope',
        422
    );
    $atlas_invalid_schema = $atlas_unchanged_body;
    $atlas_invalid_schema['payload']['schema_version'] = 'invalid';
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_invalid_schema)),
        'atlas_v5_page_payload_validation_failed',
        422
    );
    $atlas_identity_mismatch = $atlas_unchanged_body;
    $atlas_identity_mismatch['generated_page_id'] = 42;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_identity_mismatch)),
        'atlas_v5_page_payload_atlas_identity_mismatch',
        422
    );
    $atlas_planned_mismatch = $atlas_unchanged_body;
    $atlas_planned_mismatch['planned_page_id'] = 42;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_planned_mismatch)),
        'atlas_v5_page_payload_atlas_identity_mismatch',
        422
    );
    $atlas_missing_planned = $atlas_unchanged_body;
    $atlas_missing_planned['payload']['payload_identity']['frozen_inputs'] = array_values(
        array_filter(
            $atlas_missing_planned['payload']['payload_identity']['frozen_inputs'],
            static fn($value): bool => !str_starts_with((string) ($value['path'] ?? ''), 'atlas/planned-page/')
        )
    );
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_missing_planned)),
        'atlas_v5_page_payload_atlas_identity_mismatch',
        422
    );
    $atlas_duplicate_planned = $atlas_unchanged_body;
    $atlas_duplicate_planned['payload']['payload_identity']['frozen_inputs'][] = [
        'path' => 'atlas/planned-page/42',
        'sha256' => str_repeat('9', 64),
    ];
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_duplicate_planned)),
        'atlas_v5_page_payload_atlas_identity_mismatch',
        422
    );
    $atlas_malformed_planned = $atlas_unchanged_body;
    foreach ($atlas_malformed_planned['payload']['payload_identity']['frozen_inputs'] as &$atlas_input) {
        if (($atlas_input['path'] ?? null) === 'atlas/planned-page/41') {
            $atlas_input['path'] = 'atlas/planned-page/041';
        }
    }
    unset($atlas_input);
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_malformed_planned)),
        'atlas_v5_page_payload_atlas_identity_mismatch',
        422
    );
    $atlas_post_mismatch = $atlas_unchanged_body;
    $atlas_post_mismatch['wordpress_post_id'] = 9;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(atlas_route_test_request(8, $atlas_post_mismatch)),
        'atlas_v5_page_payload_post_id_mismatch',
        409
    );
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(
            atlas_route_test_request(8, $atlas_unchanged_body, str_repeat('x', 1048577))
        ),
        'atlas_v5_page_payload_body_too_large',
        413
    );
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['adds']) === 1
            && count($GLOBALS['atlas_route_test']['updates']) === 0,
        'invalid_requests_zero_writes'
    );

    $atlas_update_attempt = $atlas_payload;
    $atlas_update_attempt['page']['meta_description'] .= ' Update attempt.';
    $atlas_update_successor = $atlas_payload;
    $atlas_update_successor['page']['meta_description'] .= ' Concurrent update successor.';
    atlas_route_test_check(
        atlas_performance_local_v5_validate_payload($atlas_update_attempt) === []
            && atlas_performance_local_v5_validate_payload($atlas_update_successor) === [],
        'update_race_payloads_are_valid'
    );
    $GLOBALS['atlas_route_test']['concurrent_value'] = $atlas_update_successor;
    $GLOBALS['atlas_route_test']['arm_concurrent_before_update'] = true;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_apply(
            atlas_route_test_request(
                8,
                atlas_route_test_post_body($atlas_update_attempt, $atlas_payload_hash)
            )
        ),
        'atlas_v5_page_payload_stale_prior_state',
        409
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
            === $atlas_update_successor,
        'update_cas_preserves_concurrent_successor'
    );
    $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1'] = $atlas_payload;

    $atlas_unsafe_attempt = $atlas_payload;
    $atlas_unsafe_attempt['page']['meta_description'] .= ' Unsafe rollback attempt.';
    $atlas_unsafe_successor = $atlas_payload;
    $atlas_unsafe_successor['page']['meta_description'] .= ' Post-write concurrent successor.';
    $GLOBALS['atlas_route_test']['concurrent_value'] = $atlas_unsafe_successor;
    $GLOBALS['atlas_route_test']['arm_successor_after_update'] = true;
    $atlas_unsafe_rollback = atlas_performance_local_v5_page_payload_apply(
        atlas_route_test_request(
            8,
            atlas_route_test_post_body($atlas_unsafe_attempt, $atlas_payload_hash)
        )
    );
    atlas_route_test_error(
        $atlas_unsafe_rollback,
        'atlas_v5_page_payload_rollback_failed',
        500
    );
    atlas_route_test_check(
        ($atlas_unsafe_rollback->get_error_data()['outcome'] ?? null) === 'ROLLBACK_FAILED'
            && $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
                === $atlas_unsafe_successor
            && $GLOBALS['atlas_route_test']['rollback_updates'] === [],
        'rollback_never_overwrites_concurrent_successor'
    );
    $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1'] = $atlas_payload;

    $atlas_delete_stale = atlas_route_test_delete_body(str_repeat('0', 64));
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_remove(atlas_route_test_request(8, $atlas_delete_stale)),
        'atlas_v5_page_payload_stale_current_state',
        409
    );
    atlas_route_test_check($GLOBALS['atlas_route_test']['deletes'] === [], 'delete_stale_zero_writes');

    $atlas_delete_successor = $atlas_payload;
    $atlas_delete_successor['page']['meta_description'] .= ' Concurrent delete successor.';
    $GLOBALS['atlas_route_test']['concurrent_value'] = $atlas_delete_successor;
    $GLOBALS['atlas_route_test']['arm_concurrent_before_delete'] = true;
    atlas_route_test_error(
        atlas_performance_local_v5_page_payload_remove(
            atlas_route_test_request(8, atlas_route_test_delete_body($atlas_payload_hash))
        ),
        'atlas_v5_page_payload_stale_current_state',
        409
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
            === $atlas_delete_successor,
        'delete_cas_preserves_concurrent_successor'
    );
    $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1'] = $atlas_payload;

    $GLOBALS['atlas_route_test']['arm_false_after_delete'] = true;
    $atlas_delete_rollback = atlas_performance_local_v5_page_payload_remove(
        atlas_route_test_request(8, atlas_route_test_delete_body($atlas_payload_hash))
    );
    atlas_route_test_error(
        $atlas_delete_rollback,
        'atlas_v5_page_payload_remove_verification_failed',
        500
    );
    atlas_route_test_check(
        ($atlas_delete_rollback->get_error_data()['outcome'] ?? null) === 'ROLLED_BACK'
            && $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
                === $atlas_payload,
        'delete_verification_failure_restores_prior_payload'
    );

    $atlas_delete = atlas_route_test_delete_body($atlas_payload_hash);
    $atlas_removed = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_remove(atlas_route_test_request(8, $atlas_delete))
    );
    atlas_route_test_check($atlas_removed['status'] === 'REMOVED', 'delete_removed_status');
    atlas_route_test_check(count($GLOBALS['atlas_route_test']['deletes']) === 3, 'delete_one_normal_write');
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['deletes'][2]['meta_key'] === '_project_atlas_performance_local_v5_v1'
            && $GLOBALS['atlas_route_test']['deletes'][2]['meta_value'] === $atlas_payload,
        'delete_only_v5_key'
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_wp_page_template'] === $atlas_before_template,
        'delete_editor_template_unchanged'
    );
    $atlas_delete_absent = atlas_route_test_response_data(
        atlas_performance_local_v5_page_payload_remove(
            atlas_route_test_request(8, atlas_route_test_delete_body(null))
        )
    );
    atlas_route_test_check($atlas_delete_absent['status'] === 'UNCHANGED', 'delete_absent_unchanged');
    atlas_route_test_check(count($GLOBALS['atlas_route_test']['deletes']) === 3, 'delete_unchanged_zero_writes');

    $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1'] = $atlas_payload;
    $atlas_prior_hash = atlas_performance_local_v5_page_payload_sha256($atlas_payload);
    $atlas_changed_payload = $atlas_payload;
    $atlas_changed_payload['page']['meta_description'] .= ' Updated.';
    atlas_route_test_check(
        atlas_performance_local_v5_validate_payload($atlas_changed_payload) === [],
        'rollback_candidate_is_valid'
    );
    $GLOBALS['atlas_route_test']['arm_corrupt_after_update'] = true;
    $atlas_before_rollback_updates = count($GLOBALS['atlas_route_test']['updates']);
    $atlas_rollback = atlas_performance_local_v5_page_payload_apply(
        atlas_route_test_request(8, atlas_route_test_post_body($atlas_changed_payload, $atlas_prior_hash))
    );
    atlas_route_test_error(
        $atlas_rollback,
        'atlas_v5_page_payload_post_write_verification_failed',
        500
    );
    atlas_route_test_check(
        ($atlas_rollback->get_error_data()['outcome'] ?? null) === 'ROLLED_BACK',
        'rollback_outcome'
    );
    atlas_route_test_check(
        count($GLOBALS['atlas_route_test']['updates']) === $atlas_before_rollback_updates + 1,
        'rollback_one_forward_update'
    );
    atlas_route_test_check(count($GLOBALS['atlas_route_test']['rollback_updates']) === 1, 'rollback_one_restore');
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1'] === $atlas_payload,
        'rollback_exact_prior_payload'
    );
    atlas_route_test_check(
        atlas_performance_local_v5_page_payload_sha256(
            $GLOBALS['atlas_route_test']['meta'][8]['_project_atlas_performance_local_v5_v1']
        ) === $atlas_prior_hash,
        'rollback_exact_prior_hash'
    );
    atlas_route_test_check(
        $GLOBALS['atlas_route_test']['posts'][8] == $atlas_before_post
            && $GLOBALS['atlas_route_test']['meta'][8]['_wp_page_template'] === $atlas_before_template,
        'rollback_page_fields_unchanged'
    );

    echo json_encode([
        'case' => $atlas_case,
        'allowed' => true,
        'checks' => count($GLOBALS['atlas_route_test']['checks']),
        'route_count' => count($GLOBALS['atlas_route_test']['routes']),
        'add_call_count' => count($GLOBALS['atlas_route_test']['adds']),
        'forward_update_count' => count($GLOBALS['atlas_route_test']['updates']),
        'rollback_update_count' => count($GLOBALS['atlas_route_test']['rollback_updates']),
        'delete_count' => count($GLOBALS['atlas_route_test']['deletes']),
        'payload_sha256' => $atlas_payload_hash,
    ], JSON_UNESCAPED_SLASHES) . "\n";
} catch (Throwable $error) {
    fwrite(STDERR, json_encode([
        'case' => $atlas_case,
        'error' => $error->getMessage(),
        'checks' => $GLOBALS['atlas_route_test']['checks'],
    ], JSON_UNESCAPED_SLASHES) . "\n");
    exit(1);
}
