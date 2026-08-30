<?php
/**
 * Private, one-page-at-a-time Performance Local V5 metadata transport.
 */

if (!defined('ABSPATH')) { exit; }

define(
    'ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA',
    'project-atlas-performance-local-v5-page-payload-route@1'
);
define(
    'ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_REQUEST_SCHEMA',
    'project-atlas-performance-local-v5-page-payload-request@1'
);
define(
    'ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_DELETE_SCHEMA',
    'project-atlas-performance-local-v5-page-payload-delete@1'
);
define('ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ABSOLUTE_BODY_LIMIT', 1048576);
define('ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_BODY_HEADROOM', 65536);
define('ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_DELETE_BODY_LIMIT', 16384);

function atlas_performance_local_v5_page_payload_error(
    string $code,
    string $message,
    int $status,
    array $data = []
): WP_Error {
    return new WP_Error($code, $message, ['status' => $status] + $data);
}

/**
 * Canonical form shared with the Atlas-side request builder.
 *
 * Associative keys are recursively sorted, while list order remains governed.
 */
function atlas_performance_local_v5_page_payload_canonicalize($value) {
    if (!is_array($value)) { return $value; }
    if (array_is_list($value)) {
        return array_map('atlas_performance_local_v5_page_payload_canonicalize', $value);
    }
    ksort($value, SORT_STRING);
    foreach ($value as $key => $child) {
        $value[$key] = atlas_performance_local_v5_page_payload_canonicalize($child);
    }
    return $value;
}

function atlas_performance_local_v5_page_payload_json($value): ?string {
    $encoded = wp_json_encode(
        atlas_performance_local_v5_page_payload_canonicalize($value),
        JSON_UNESCAPED_SLASHES
            | JSON_UNESCAPED_UNICODE
            | JSON_UNESCAPED_LINE_TERMINATORS
            | JSON_PRESERVE_ZERO_FRACTION
    );
    return is_string($encoded) ? $encoded : null;
}

function atlas_performance_local_v5_page_payload_sha256($value): ?string {
    $encoded = atlas_performance_local_v5_page_payload_json($value);
    return $encoded === null ? null : hash('sha256', $encoded);
}

function atlas_performance_local_v5_page_payload_sha256_is_valid($value): bool {
    return is_string($value) && preg_match('/^[a-f0-9]{64}$/D', $value) === 1;
}

function atlas_performance_local_v5_page_payload_uuid_is_valid($value): bool {
    return is_string($value)
        && preg_match(
            '/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/Di',
            $value
        ) === 1;
}

function atlas_performance_local_v5_page_payload_positive_integer($value): bool {
    return is_int($value) && $value > 0;
}

function atlas_performance_local_v5_page_payload_exact_record($value, array $keys): bool {
    if (!is_array($value) || array_is_list($value)) { return false; }
    $actual = array_keys($value);
    sort($actual, SORT_STRING);
    sort($keys, SORT_STRING);
    return $actual === $keys;
}

function atlas_performance_local_v5_page_payload_planned_page_input_matches(
    array $payload,
    int $planned_page_id
): bool {
    $inputs = $payload['payload_identity']['frozen_inputs'] ?? null;
    if (!is_array($inputs) || !array_is_list($inputs)) { return false; }
    $planned_inputs = 0;
    $expected_path = 'atlas/planned-page/' . $planned_page_id;
    $expected_found = false;
    foreach ($inputs as $input) {
        if (!is_array($input) || !isset($input['path']) || !is_string($input['path'])) {
            return false;
        }
        if (!str_starts_with($input['path'], 'atlas/planned-page/')) {
            continue;
        }
        if (preg_match('#^atlas/planned-page/[1-9][0-9]*$#D', $input['path']) !== 1) {
            return false;
        }
        $planned_inputs++;
        if ($input['path'] === $expected_path
            && atlas_performance_local_v5_page_payload_sha256_is_valid($input['sha256'] ?? null)) {
            $expected_found = true;
        }
    }
    return $planned_inputs === 1 && $expected_found;
}

function atlas_performance_local_v5_page_payload_route_post_id(WP_REST_Request $request): int|WP_Error {
    $raw = $request->get_param('post_id');
    if ((!is_int($raw) && !is_string($raw)) || preg_match('/^[1-9][0-9]*$/D', (string) $raw) !== 1) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_post_id',
            'A positive canonical WordPress post ID is required.',
            400
        );
    }
    $post_id = (int) $raw;
    if ($post_id < 1 || (string) $post_id !== (string) $raw) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_post_id',
            'A positive canonical WordPress post ID is required.',
            400
        );
    }
    return $post_id;
}

function atlas_performance_local_v5_page_payload_target(WP_REST_Request $request): WP_Post|WP_Error {
    $post_id = atlas_performance_local_v5_page_payload_route_post_id($request);
    if (is_wp_error($post_id)) { return $post_id; }
    $post = get_post($post_id);
    if (!$post) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_post_not_found',
            'The requested WordPress post does not exist.',
            404
        );
    }
    if ($post->post_type !== 'page') {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_wrong_post_type',
            'The requested WordPress post is not a page.',
            409
        );
    }
    return $post;
}

function atlas_performance_local_v5_page_payload_permission(WP_REST_Request $request): bool|WP_Error {
    if (!atlas_performance_local_v5_environment_is_allowed()) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_environment_denied',
            'This operation is unavailable in the current WordPress environment.',
            403
        );
    }
    if (!is_user_logged_in()) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_authentication_required',
            'Authenticated WordPress REST access is required.',
            401
        );
    }
    if (!current_user_can('manage_options')) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_manage_options_required',
            'The authenticated user cannot manage this operation.',
            403
        );
    }
    $target = atlas_performance_local_v5_page_payload_target($request);
    if (is_wp_error($target)) { return $target; }
    if (!current_user_can('edit_post', (int) $target->ID)) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_edit_post_required',
            'The authenticated user cannot edit the requested page.',
            403
        );
    }
    return true;
}

function atlas_performance_local_v5_page_payload_register_route(): void {
    register_rest_route(
        'project-atlas/v4',
        '/performance-local-v5/page-payload/(?P<post_id>\d+)',
        [
            [
                'methods' => 'GET',
                'permission_callback' => 'atlas_performance_local_v5_page_payload_permission',
                'callback' => 'atlas_performance_local_v5_page_payload_inspect',
            ],
            [
                'methods' => 'POST',
                'permission_callback' => 'atlas_performance_local_v5_page_payload_permission',
                'callback' => 'atlas_performance_local_v5_page_payload_apply',
            ],
            [
                'methods' => 'DELETE',
                'permission_callback' => 'atlas_performance_local_v5_page_payload_permission',
                'callback' => 'atlas_performance_local_v5_page_payload_remove',
            ],
        ]
    );
}
add_action('rest_api_init', 'atlas_performance_local_v5_page_payload_register_route');

function atlas_performance_local_v5_page_payload_metadata_state(int $post_id): array {
    $exists = metadata_exists('post', $post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY);
    $value = $exists ? get_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, true) : null;
    $sha256 = $exists ? atlas_performance_local_v5_page_payload_sha256($value) : null;
    $errors = $exists && is_array($value)
        ? atlas_performance_local_v5_validate_payload($value)
        : ['No valid V5 payload is present.'];
    return [
        'exists' => $exists,
        'value' => $value,
        'sha256' => $sha256,
        'valid' => $exists && $sha256 !== null && $errors === [],
        'errors' => $errors,
    ];
}

function atlas_performance_local_v5_page_payload_atlas_identity(array $state): ?array {
    if (!$state['valid'] || !is_array($state['value'])) { return null; }
    $payload = $state['value'];
    $website_identity = $payload['website']['identity'] ?? null;
    $source_page = $payload['payload_identity']['source_page'] ?? null;
    if (!is_string($website_identity)
        || preg_match('/^website:([1-9][0-9]*)$/D', $website_identity, $website_match) !== 1
        || !is_string($source_page)
        || preg_match('/^generated-page:([1-9][0-9]*)$/D', $source_page, $page_match) !== 1) {
        return null;
    }
    return [
        'website_id' => (int) $website_match[1],
        'generated_page_id' => (int) $page_match[1],
        'source_composition' => (string) $payload['payload_identity']['source_composition'],
        'source_sha256' => (string) $payload['payload_identity']['source_hash'],
    ];
}

function atlas_performance_local_v5_page_payload_inspect(WP_REST_Request $request) {
    $target = atlas_performance_local_v5_page_payload_target($request);
    if (is_wp_error($target)) { return $target; }
    $state = atlas_performance_local_v5_page_payload_metadata_state((int) $target->ID);
    return rest_ensure_response([
        'route_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA,
        'metadata_bridge_version' => ATLAS_METADATA_BRIDGE_VERSION,
        'environment_type' => wp_get_environment_type(),
        'home' => esc_url_raw((string) get_option('home', '')),
        'siteurl' => esc_url_raw((string) get_option('siteurl', '')),
        'blog_public' => (int) get_option('blog_public', 1),
        'post_id' => (int) $target->ID,
        'post_type' => (string) $target->post_type,
        'post_status' => (string) $target->post_status,
        'post_title' => trim(wp_strip_all_tags((string) $target->post_title)),
        'post_slug' => (string) $target->post_name,
        'metadata_exists' => (bool) $state['exists'],
        'metadata_sha256' => $state['sha256'],
        'metadata_valid' => (bool) $state['valid'],
        'atlas_identity' => atlas_performance_local_v5_page_payload_atlas_identity($state),
    ]);
}

function atlas_performance_local_v5_page_payload_request_size(
    WP_REST_Request $request,
    int $limit
): int|WP_Error {
    $raw = $request->get_body();
    $body_bytes = is_string($raw) ? strlen($raw) : 0;
    $header = trim((string) $request->get_header('content-length'));
    if ($header !== '' && preg_match('/^(?:0|[1-9][0-9]*)$/D', $header) !== 1) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_content_length',
            'Content-Length is invalid.',
            400
        );
    }
    if ($header !== '') { $body_bytes = max($body_bytes, (int) $header); }
    if ($body_bytes > $limit) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_body_too_large',
            'The request body exceeds the allowed size.',
            413,
            ['maximum_body_bytes' => $limit]
        );
    }
    return $body_bytes;
}

function atlas_performance_local_v5_page_payload_post_envelope(
    WP_REST_Request $request,
    int $route_post_id
): array|WP_Error {
    $body_bytes = atlas_performance_local_v5_page_payload_request_size(
        $request,
        ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ABSOLUTE_BODY_LIMIT
    );
    if (is_wp_error($body_bytes)) { return $body_bytes; }
    $body = $request->get_json_params();
    $keys = [
        'request_schema', 'expected_prior_sha256', 'website_id', 'planned_page_id',
        'generated_page_id', 'wordpress_post_id', 'payload', 'request_identity',
    ];
    if (!atlas_performance_local_v5_page_payload_exact_record($body, $keys)) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_envelope',
            'The request envelope differs from the exact contract.',
            422
        );
    }
    if ($body['request_schema'] !== ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_REQUEST_SCHEMA
        || !atlas_performance_local_v5_page_payload_positive_integer($body['website_id'])
        || !atlas_performance_local_v5_page_payload_positive_integer($body['planned_page_id'])
        || !atlas_performance_local_v5_page_payload_positive_integer($body['generated_page_id'])
        || !atlas_performance_local_v5_page_payload_positive_integer($body['wordpress_post_id'])
        || !atlas_performance_local_v5_page_payload_uuid_is_valid($body['request_identity'])
        || ($body['expected_prior_sha256'] !== null
            && !atlas_performance_local_v5_page_payload_sha256_is_valid($body['expected_prior_sha256']))) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_envelope',
            'The request envelope contains an invalid identity or hash.',
            422
        );
    }
    if ($body['wordpress_post_id'] !== $route_post_id) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_post_id_mismatch',
            'The route and request WordPress post identities differ.',
            409
        );
    }
    if (!is_array($body['payload'])) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_payload',
            'The governed V5 payload is invalid.',
            422,
            ['validation_errors' => ['Payload must be an object.']]
        );
    }
    $payload_json = atlas_performance_local_v5_page_payload_json($body['payload']);
    if ($payload_json === null) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_payload',
            'The governed V5 payload cannot be encoded.',
            422
        );
    }
    $effective_limit = min(
        ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ABSOLUTE_BODY_LIMIT,
        strlen($payload_json) + ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_BODY_HEADROOM
    );
    if ($body_bytes > $effective_limit) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_body_too_large',
            'The request body exceeds the payload-bound size limit.',
            413,
            ['maximum_body_bytes' => $effective_limit]
        );
    }
    $errors = atlas_performance_local_v5_validate_payload($body['payload']);
    if ($errors !== []) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_validation_failed',
            'The governed V5 payload failed validation.',
            422,
            ['validation_errors' => array_values($errors)]
        );
    }
    if (atlas_performance_local_v5_page_payload_contains_private_delivery_value($body['payload'])) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_private_delivery_value',
            'The governed V5 payload contains a private delivery identity.',
            422
        );
    }
    // The sealed renderer has no top-level Planned Page field, so the transport
    // binds it through exactly one canonical frozen-input path. Planned and
    // Generated Page identities are deliberately independent.
    if (($body['payload']['schema_version'] ?? null) !== ATLAS_PERFORMANCE_LOCAL_V5_SCHEMA
        || ($body['payload']['rehearsal_only'] ?? null) !== true
        || ($body['payload']['website']['identity'] ?? null) !== 'website:' . $body['website_id']
        || ($body['payload']['payload_identity']['source_page'] ?? null)
            !== 'generated-page:' . $body['generated_page_id']
        || !atlas_performance_local_v5_page_payload_planned_page_input_matches(
            $body['payload'],
            $body['planned_page_id']
        )) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_atlas_identity_mismatch',
            'The Atlas request and payload identities differ.',
            422
        );
    }
    return $body;
}

function atlas_performance_local_v5_page_payload_delete_envelope(
    WP_REST_Request $request,
    int $route_post_id
): array|WP_Error {
    $body_bytes = atlas_performance_local_v5_page_payload_request_size(
        $request,
        ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_DELETE_BODY_LIMIT
    );
    if (is_wp_error($body_bytes)) { return $body_bytes; }
    $body = $request->get_json_params();
    if (!atlas_performance_local_v5_page_payload_exact_record(
        $body,
        ['request_schema', 'expected_current_sha256', 'wordpress_post_id', 'request_identity']
    )
        || $body['request_schema'] !== ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_DELETE_SCHEMA
        || !atlas_performance_local_v5_page_payload_positive_integer($body['wordpress_post_id'])
        || !atlas_performance_local_v5_page_payload_uuid_is_valid($body['request_identity'])
        || ($body['expected_current_sha256'] !== null
            && !atlas_performance_local_v5_page_payload_sha256_is_valid($body['expected_current_sha256']))) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_invalid_delete_envelope',
            'The removal envelope differs from the exact contract.',
            422
        );
    }
    if ($body['wordpress_post_id'] !== $route_post_id) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_post_id_mismatch',
            'The route and request WordPress post identities differ.',
            409
        );
    }
    return $body;
}

function atlas_performance_local_v5_page_payload_protected_post_state(WP_Post $post): array {
    return [
        'post_type' => (string) $post->post_type,
        'post_status' => (string) $post->post_status,
        'post_title' => (string) $post->post_title,
        'post_name' => (string) $post->post_name,
        'post_content' => (string) $post->post_content,
        'post_excerpt' => (string) $post->post_excerpt,
        'post_author' => (int) $post->post_author,
        'post_parent' => (int) $post->post_parent,
        'menu_order' => (int) $post->menu_order,
        'featured_image' => (int) get_post_thumbnail_id((int) $post->ID),
        'template_exists' => metadata_exists('post', (int) $post->ID, '_wp_page_template'),
        'template_value' => get_post_meta((int) $post->ID, '_wp_page_template', true),
    ];
}

function atlas_performance_local_v5_page_payload_contains_private_delivery_value(array $payload): bool {
    $option_key = defined('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION')
        ? ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION
        : '_project_atlas_estimate_form_delivery_v1';
    $configuration = get_option($option_key, null);
    if (!is_array($configuration)) { return false; }

    $private_values = [];
    foreach (['recipient_email', 'from_email'] as $key) {
        $value = $configuration[$key] ?? null;
        if (is_string($value) && trim($value) !== '') {
            $private_values[] = strtolower(trim($value));
        }
    }
    if ($private_values === []) { return false; }

    $encoded = atlas_performance_local_v5_page_payload_json($payload);
    if ($encoded === null) { return true; }
    $encoded = strtolower($encoded);
    foreach ($private_values as $private_value) {
        if (str_contains($encoded, $private_value)) { return true; }
    }
    return false;
}

function atlas_performance_local_v5_page_payload_matches_state(
    array $state,
    bool $expected_exists,
    $expected_value,
    ?string $expected_sha256
): bool {
    return $state['exists'] === $expected_exists
        && $state['sha256'] === $expected_sha256
        && (!$expected_exists || $state['value'] === $expected_value);
}

function atlas_performance_local_v5_page_payload_target_matches_payload(
    WP_Post $post,
    array $payload
): bool {
    return $post->post_type === 'page'
        && $post->post_status === 'publish'
        && (string) $post->post_title === (string) ($payload['page']['title'] ?? '')
        && (string) $post->post_name === (string) ($payload['page']['slug'] ?? '');
}

function atlas_performance_local_v5_page_payload_restore(
    int $post_id,
    bool $prior_exists,
    $prior_value,
    ?string $prior_sha256,
    $attempted_value,
    ?string $attempted_sha256
): bool {
    $current = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    if (atlas_performance_local_v5_page_payload_matches_state(
        $current,
        $prior_exists,
        $prior_value,
        $prior_sha256
    )) { return true; }
    if (!atlas_performance_local_v5_page_payload_matches_state(
        $current,
        true,
        $attempted_value,
        $attempted_sha256
    )) { return false; }

    if ($prior_exists) {
        update_metadata(
            'post',
            $post_id,
            ATLAS_PERFORMANCE_LOCAL_V5_META_KEY,
            $prior_value,
            $attempted_value
        );
    } else {
        delete_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, $attempted_value);
    }
    $restored = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    return atlas_performance_local_v5_page_payload_matches_state(
        $restored,
        $prior_exists,
        $prior_value,
        $prior_sha256
    );
}

function atlas_performance_local_v5_page_payload_restore_deleted(
    int $post_id,
    $prior_value,
    ?string $prior_sha256
): bool {
    $current = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    if (atlas_performance_local_v5_page_payload_matches_state(
        $current,
        true,
        $prior_value,
        $prior_sha256
    )) { return true; }
    if ($current['exists']) { return false; }

    add_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, $prior_value, true);
    $restored = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    return atlas_performance_local_v5_page_payload_matches_state(
        $restored,
        true,
        $prior_value,
        $prior_sha256
    );
}

function atlas_performance_local_v5_page_payload_apply(WP_REST_Request $request) {
    $target = atlas_performance_local_v5_page_payload_target($request);
    if (is_wp_error($target)) { return $target; }
    $post_id = (int) $target->ID;
    $body = atlas_performance_local_v5_page_payload_post_envelope($request, $post_id);
    if (is_wp_error($body)) { return $body; }

    $payload = $body['payload'];
    $resulting_sha256 = atlas_performance_local_v5_page_payload_sha256($payload);
    $prior = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    $fresh_target = get_post($post_id);
    if (!($fresh_target instanceof WP_Post)
        || !atlas_performance_local_v5_page_payload_target_matches_payload($fresh_target, $payload)) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_target_identity_changed',
            'The target page identity or renderer-required status changed before the metadata write.',
            409
        );
    }
    // State idempotency comes before stale-prior rejection so an exact retry of
    // a request whose success response was lost performs no second write.
    if ($prior['valid']
        && $prior['sha256'] === $resulting_sha256
        && atlas_performance_local_v5_page_payload_json($prior['value'])
            === atlas_performance_local_v5_page_payload_json($payload)) {
        return rest_ensure_response([
            'route_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA,
            'metadata_bridge_version' => ATLAS_METADATA_BRIDGE_VERSION,
            'status' => 'UNCHANGED',
            'post_id' => $post_id,
            'prior_sha256' => $prior['sha256'],
            'resulting_sha256' => $resulting_sha256,
            'website_id' => $body['website_id'],
            'planned_page_id' => $body['planned_page_id'],
            'generated_page_id' => $body['generated_page_id'],
            'request_identity' => $body['request_identity'],
            'metadata_valid' => true,
        ]);
    }
    $expected = $body['expected_prior_sha256'];
    if (($expected === null && $prior['exists'])
        || ($expected !== null && (!$prior['exists'] || !hash_equals($expected, (string) $prior['sha256'])))) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_stale_prior_state',
            'The expected prior V5 metadata state is stale.',
            409,
            ['current_sha256' => $prior['sha256']]
        );
    }

    $protected_before = atlas_performance_local_v5_page_payload_protected_post_state($fresh_target);
    $write_result = $prior['exists']
        ? update_post_meta(
            $post_id,
            ATLAS_PERFORMANCE_LOCAL_V5_META_KEY,
            $payload,
            $prior['value']
        )
        : add_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, $payload, true);
    if ($write_result === false) {
        $current = atlas_performance_local_v5_page_payload_metadata_state($post_id);
        if (!atlas_performance_local_v5_page_payload_matches_state(
            $current,
            (bool) $prior['exists'],
            $prior['value'],
            $prior['sha256']
        )) {
            return atlas_performance_local_v5_page_payload_error(
                'atlas_v5_page_payload_stale_prior_state',
                'The expected prior V5 metadata state changed before the metadata write.',
                409,
                ['current_sha256' => $current['sha256']]
            );
        }
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_write_failed',
            'The V5 metadata write failed without changing the prior state.',
            500,
            ['current_sha256' => $current['sha256']]
        );
    }
    $readback = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    $post_after = get_post($post_id);
    $verified = $write_result !== false
        && $readback['exists']
        && $readback['value'] === $payload
        && $readback['sha256'] === $resulting_sha256
        && $readback['valid']
        && $post_after instanceof WP_Post
        && atlas_performance_local_v5_page_payload_protected_post_state($post_after) === $protected_before;
    if (!$verified) {
        $rolled_back = atlas_performance_local_v5_page_payload_restore(
            $post_id,
            (bool) $prior['exists'],
            $prior['value'],
            $prior['sha256'],
            $payload,
            $resulting_sha256
        );
        return atlas_performance_local_v5_page_payload_error(
            $rolled_back
                ? 'atlas_v5_page_payload_post_write_verification_failed'
                : 'atlas_v5_page_payload_rollback_failed',
            $rolled_back
                ? 'Post-write verification failed and the prior metadata state was restored.'
                : 'Post-write verification and metadata rollback both failed.',
            500,
            [
                'outcome' => $rolled_back ? 'ROLLED_BACK' : 'ROLLBACK_FAILED',
                'prior_sha256' => $prior['sha256'],
                'attempted_sha256' => $resulting_sha256,
            ]
        );
    }

    return rest_ensure_response([
        'route_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA,
        'metadata_bridge_version' => ATLAS_METADATA_BRIDGE_VERSION,
        'status' => 'APPLIED',
        'post_id' => $post_id,
        'prior_sha256' => $prior['sha256'],
        'resulting_sha256' => $resulting_sha256,
        'website_id' => $body['website_id'],
        'planned_page_id' => $body['planned_page_id'],
        'generated_page_id' => $body['generated_page_id'],
        'request_identity' => $body['request_identity'],
        'metadata_valid' => true,
    ]);
}

function atlas_performance_local_v5_page_payload_remove(WP_REST_Request $request) {
    $target = atlas_performance_local_v5_page_payload_target($request);
    if (is_wp_error($target)) { return $target; }
    $post_id = (int) $target->ID;
    $body = atlas_performance_local_v5_page_payload_delete_envelope($request, $post_id);
    if (is_wp_error($body)) { return $body; }
    $prior = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    $expected = $body['expected_current_sha256'];
    if (($expected === null && $prior['exists'])
        || ($expected !== null && (!$prior['exists'] || !hash_equals($expected, (string) $prior['sha256'])))) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_stale_current_state',
            'The expected current V5 metadata state is stale.',
            409,
            ['current_sha256' => $prior['sha256']]
        );
    }
    if (!$prior['exists']) {
        return rest_ensure_response([
            'route_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA,
            'metadata_bridge_version' => ATLAS_METADATA_BRIDGE_VERSION,
            'status' => 'UNCHANGED',
            'post_id' => $post_id,
            'prior_sha256' => null,
            'resulting_sha256' => null,
            'request_identity' => $body['request_identity'],
        ]);
    }

    $fresh_target = get_post($post_id);
    if (!($fresh_target instanceof WP_Post)
        || ($prior['valid']
            && !atlas_performance_local_v5_page_payload_target_matches_payload(
                $fresh_target,
                $prior['value']
            ))) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_target_identity_changed',
            'The target page identity or renderer-required status changed before metadata removal.',
            409
        );
    }
    $protected_before = atlas_performance_local_v5_page_payload_protected_post_state($fresh_target);
    $deleted = delete_post_meta(
        $post_id,
        ATLAS_PERFORMANCE_LOCAL_V5_META_KEY,
        $prior['value']
    );
    $after = atlas_performance_local_v5_page_payload_metadata_state($post_id);
    $post_after = get_post($post_id);
    if ($deleted === false
        && $after['exists']
        && !atlas_performance_local_v5_page_payload_matches_state(
            $after,
            true,
            $prior['value'],
            $prior['sha256']
        )) {
        return atlas_performance_local_v5_page_payload_error(
            'atlas_v5_page_payload_stale_current_state',
            'The expected current V5 metadata state changed before removal.',
            409,
            ['current_sha256' => $after['sha256']]
        );
    }
    if ($deleted === false || $after['exists']
        || !($post_after instanceof WP_Post)
        || atlas_performance_local_v5_page_payload_protected_post_state($post_after) !== $protected_before) {
        $rolled_back = atlas_performance_local_v5_page_payload_restore_deleted(
            $post_id,
            $prior['value'],
            $prior['sha256']
        );
        return atlas_performance_local_v5_page_payload_error(
            $rolled_back
                ? 'atlas_v5_page_payload_remove_verification_failed'
                : 'atlas_v5_page_payload_remove_rollback_failed',
            $rolled_back
                ? 'V5 metadata removal could not be verified and the prior metadata state was restored.'
                : 'V5 metadata removal could not be verified and the prior state could not be safely restored.',
            500,
            [
                'outcome' => $rolled_back ? 'ROLLED_BACK' : 'ROLLBACK_FAILED',
                'prior_sha256' => $prior['sha256'],
                'current_sha256' => $after['sha256'],
            ]
        );
    }
    return rest_ensure_response([
        'route_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA,
        'metadata_bridge_version' => ATLAS_METADATA_BRIDGE_VERSION,
        'status' => 'REMOVED',
        'post_id' => $post_id,
        'prior_sha256' => $prior['sha256'],
        'resulting_sha256' => null,
        'request_identity' => $body['request_identity'],
    ]);
}
