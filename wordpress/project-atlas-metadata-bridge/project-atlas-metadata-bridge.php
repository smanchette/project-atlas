<?php
/**
 * Plugin Name: Project Atlas Metadata Bridge
 * Description: Guarded Orlando-only metadata rendering bridge for Project Atlas.
 * Version: 0.57.5
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Author: Project Atlas
 */

if (!defined('ABSPATH')) { exit; }

define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.5');
define('ATLAS_METADATA_POST_ID', 8);
define('ATLAS_METADATA_MEDIA_ID', 31);
define('ATLAS_METADATA_EXCLUDED_MEDIA_ID', 32);
define('ATLAS_METADATA_SAFETY_OPTION', '_project_atlas_metadata_safety_v1');

function atlas_metadata_plugin_checksum(): string { return hash_file('sha256', __FILE__); }

function atlas_metadata_activate(): void {
    update_option(ATLAS_METADATA_SAFETY_OPTION, [
        'activation_generation' => wp_generate_uuid4(), 'enabled' => false,
        'authorized_generation' => '', 'plugin_version' => ATLAS_METADATA_BRIDGE_VERSION,
        'plugin_checksum' => atlas_metadata_plugin_checksum(),
    ], false);
}
register_activation_hook(__FILE__, 'atlas_metadata_activate');

function atlas_metadata_permission(): bool {
    return current_user_can('edit_post', ATLAS_METADATA_POST_ID) && current_user_can('manage_options');
}

function atlas_metadata_snapshot(): array {
    $payload = get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_payload', true);
    $safety = get_option(ATLAS_METADATA_SAFETY_OPTION, []);
    $authorized = is_array($safety) && !empty($safety['enabled'])
        && hash_equals((string)($safety['activation_generation'] ?? ''), (string)($safety['authorized_generation'] ?? ''))
        && hash_equals(ATLAS_METADATA_BRIDGE_VERSION, (string)($safety['plugin_version'] ?? ''))
        && hash_equals(atlas_metadata_plugin_checksum(), (string)($safety['plugin_checksum'] ?? ''));
    return [
        'rendering_enabled' => $authorized && get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_enabled', true) === '1',
        'enabled_metadata_state' => get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_enabled', true) === '1',
        'activation_generation' => (string)($safety['activation_generation'] ?? ''),
        'plugin_checksum' => atlas_metadata_plugin_checksum(),
        'payload_hash' => (string) get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_payload_hash', true),
        'revision' => (string) (get_post_meta(ATLAS_METADATA_POST_ID, '_atlas_metadata_revision', true) ?: '0'),
        'payload' => is_array($payload) ? $payload : null,
    ];
}

function atlas_metadata_canonicalize($value) {
    if (is_array($value)) {
        if (array_keys($value) !== range(0, count($value) - 1)) { ksort($value); }
        foreach ($value as $key => $item) { $value[$key] = atlas_metadata_canonicalize($item); }
    }
    return $value;
}

function atlas_metadata_hash(array $payload): string {
    return hash('sha256', wp_json_encode(atlas_metadata_canonicalize($payload), JSON_UNESCAPED_SLASHES));
}

function atlas_metadata_approved_payload(): array {
    $url = 'https://www.drywoodtenting.com/drywood-termite-tenting-orlando-fl/';
    $description = 'Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida.';
    $organization = 'Flo-Zone Pest And Termite Solutions Inc';
    $organization_id = 'https://www.drywoodtenting.com/#organization';
    return ['schema_version'=>'2.0','page_id'=>41,'wordpress_post_id'=>8,'meta_description'=>$description,
        'json_ld'=>['@context'=>'https://schema.org','@graph'=>[
            ['@type'=>'Organization','@id'=>$organization_id,'name'=>$organization,'telephone'=>'(844) 600-8368','email'=>'Office@Flo-ZoneTenting.com','identifier'=>['@type'=>'PropertyValue','name'=>'License','value'=>'JB360566']],
            ['@type'=>'Service','@id'=>$url.'#service','serviceType'=>'Drywood termite tenting','areaServed'=>'Orlando, Florida','provider'=>['@id'=>$organization_id]],
        ]]];
}

function atlas_metadata_validate_images($value, string $key = ''): array {
    $errors = []; $approved = 'https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png';
    $excluded_filename = 'orlando-drywood-termite-tenting-hero-1.png';
    if (is_array($value)) {
        foreach ($value as $child_key => $child) { $errors = array_merge($errors, atlas_metadata_validate_images($child, strtolower((string)$child_key))); }
    } elseif (is_string($value)) {
        $lower = strtolower($value);
        if (str_contains($lower, $excluded_filename) || str_contains($lower, 'attachment:32') || str_contains($lower, 'media:32')) { $errors[] = 'Excluded media 32 appears in the payload.'; }
        if ((str_contains($key, 'image') || str_contains($lower, '/uploads/')) && filter_var($value, FILTER_VALIDATE_URL) && $value !== $approved && !str_ends_with($value, '#primaryimage')) { $errors[] = 'A non-media-31 image URL was found.'; }
        if ((str_contains($key, 'image') || str_contains($key, 'media') || str_contains($key, 'attachment')) && $value === '32') { $errors[] = 'Excluded media identifier 32 found.'; }
    } elseif (is_int($value) && (str_contains($key, 'image') || str_contains($key, 'media') || str_contains($key, 'attachment')) && $value !== 31) {
        if ($value === 32) { $errors[] = 'Excluded media identifier 32 found.'; }
    }
    return $errors;
}

function atlas_metadata_validate_payload($payload): array {
    $errors = [];
    if (!is_array($payload) || atlas_metadata_canonicalize($payload) !== atlas_metadata_canonicalize(atlas_metadata_approved_payload())) { $errors[] = 'Payload is not the complete approved Orlando metadata payload.'; }
    $errors = array_merge($errors, atlas_metadata_validate_images($payload));
    return $errors;
}

add_action('rest_api_init', function (): void {
    register_rest_route('project-atlas/v1', '/status', [
        'methods' => 'GET', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => fn() => rest_ensure_response(['plugin' => 'project-atlas-metadata-bridge', 'version' => ATLAS_METADATA_BRIDGE_VERSION, 'checksum' => atlas_metadata_plugin_checksum(), 'active' => true, 'snapshot' => atlas_metadata_snapshot()] + atlas_metadata_snapshot()),
    ]);
    register_rest_route('project-atlas/v1', '/pages/8/metadata/validate', [
        'methods' => 'POST', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => function (WP_REST_Request $request) {
            $payload = $request->get_json_params()['payload'] ?? null;
            $errors = atlas_metadata_validate_payload($payload);
            return rest_ensure_response(['valid' => !$errors, 'errors' => $errors, 'payload_hash' => is_array($payload) ? atlas_metadata_hash($payload) : null, 'read_only' => true]);
        },
    ]);
    register_rest_route('project-atlas/v1', '/pages/8/metadata', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_apply',
    ]);
    register_rest_route('project-atlas/v1', '/pages/8/metadata/rendered', [
        'methods' => 'GET', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => fn() => rest_ensure_response(atlas_metadata_snapshot() + ['post_id' => 8, 'read_only' => true]),
    ]);
    register_rest_route('project-atlas/v1', '/pages/8/metadata/rollback', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_rollback',
    ]);
    register_rest_route('project-atlas/v2', '/pages/8/metadata/stage', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_stage',
    ]);
    register_rest_route('project-atlas/v2', '/pages/8/metadata/rendering/enable', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_rendering_enable',
    ]);
    register_rest_route('project-atlas/v2', '/pages/8/metadata/rendering/disable', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_rendering_disable',
    ]);
    register_rest_route('project-atlas/v2', '/pages/8/metadata/stage/rollback', [
        'methods' => 'PUT', 'permission_callback' => 'atlas_metadata_permission',
        'callback' => 'atlas_metadata_stage_rollback',
    ]);
});

function atlas_metadata_apply(WP_REST_Request $request) {
    return new WP_Error('atlas_legacy_combined_apply_disabled', 'The combined payload-and-rendering endpoint is deprecated and disabled. Use the separated v2 lifecycle.', ['status' => 410]);
}

function atlas_metadata_snapshot_hash(array $snapshot): string {
    $bound = [];
    foreach (['rendering_enabled','enabled_metadata_state','activation_generation','plugin_checksum','payload_hash','revision','payload'] as $key) { $bound[$key] = $snapshot[$key] ?? null; }
    return hash('sha256', wp_json_encode(atlas_metadata_canonicalize($bound), JSON_UNESCAPED_SLASHES));
}

function atlas_metadata_lifecycle_request(WP_REST_Request $request): array|WP_Error {
    $body = $request->get_json_params(); $payload = $body['payload'] ?? null; $expected_hash = (string) ($body['payload_hash'] ?? '');
    $snapshot = atlas_metadata_snapshot();
    if (!hash_equals($snapshot['revision'], (string) ($body['expected_revision'] ?? ''))) { return new WP_Error('atlas_revision_conflict', 'Metadata revision changed.', ['status' => 409]); }
    if (!hash_equals(atlas_metadata_snapshot_hash($snapshot), (string)($body['expected_snapshot_hash'] ?? ''))) { return new WP_Error('atlas_snapshot_conflict', 'Metadata snapshot changed.', ['status' => 409]); }
    $post = get_post(8); if (!$post || $post->post_status !== 'publish' || $post->post_name !== 'drywood-termite-tenting-orlando-fl') { return new WP_Error('atlas_post_changed', 'Orlando post identity changed.', ['status' => 409]); }
    if ((int) get_post_thumbnail_id(8) !== 31 || get_post(31) === null || get_post(32) === null) { return new WP_Error('atlas_media_changed', 'Expected media state changed.', ['status' => 409]); }
    return ['body'=>$body, 'payload'=>$payload, 'expected_hash'=>$expected_hash, 'snapshot'=>$snapshot];
}

function atlas_metadata_stage(WP_REST_Request $request) {
    $context = atlas_metadata_lifecycle_request($request); if (is_wp_error($context)) { return $context; }
    ['payload'=>$payload,'expected_hash'=>$expected_hash,'snapshot'=>$snapshot] = $context;
    $errors = atlas_metadata_validate_payload($payload);
    if ($errors) { return new WP_Error('atlas_invalid_payload', implode(' ', $errors), ['status' => 422]); }
    if ($snapshot['rendering_enabled'] || $snapshot['payload'] !== null || $snapshot['payload_hash'] !== '' || $snapshot['revision'] !== '0') { return new WP_Error('atlas_stage_state_conflict', 'Initial staging state changed.', ['status' => 409]); }
    if (!hash_equals(atlas_metadata_hash($payload), $expected_hash)) { return new WP_Error('atlas_hash_mismatch', 'Payload hash mismatch.', ['status' => 409]); }
    update_post_meta(8, '_atlas_metadata_payload', $payload);
    update_post_meta(8, '_atlas_metadata_payload_hash', $expected_hash);
    update_post_meta(8, '_atlas_metadata_revision', '1');
    delete_post_meta(8, '_atlas_metadata_enabled');
    return rest_ensure_response(['status'=>'metadata_staged','post_id'=>8,'payload_hash'=>$expected_hash,'revision'=>'1','rendering_enabled'=>false]);
}

function atlas_metadata_rendering_enable(WP_REST_Request $request) {
    $context = atlas_metadata_lifecycle_request($request); if (is_wp_error($context)) { return $context; }
    ['expected_hash'=>$expected_hash,'snapshot'=>$snapshot] = $context;
    if ($snapshot['rendering_enabled'] || $snapshot['revision'] !== '1' || !is_array($snapshot['payload']) || !hash_equals($snapshot['payload_hash'], $expected_hash) || atlas_metadata_validate_payload($snapshot['payload'])) { return new WP_Error('atlas_enable_state_conflict', 'Exact disabled staged payload required.', ['status' => 409]); }
    update_post_meta(8, '_atlas_metadata_enabled', '1');
    update_option(ATLAS_METADATA_SAFETY_OPTION, ['activation_generation'=>$snapshot['activation_generation'],'enabled'=>true,'authorized_generation'=>$snapshot['activation_generation'],'plugin_version'=>ATLAS_METADATA_BRIDGE_VERSION,'plugin_checksum'=>atlas_metadata_plugin_checksum()], false);
    return rest_ensure_response(['status'=>'metadata_rendering_enabled','post_id'=>8,'payload_hash'=>$expected_hash,'revision'=>'1','rendering_enabled'=>true]);
}

function atlas_metadata_rendering_disable(WP_REST_Request $request) {
    $context = atlas_metadata_lifecycle_request($request); if (is_wp_error($context)) { return $context; }
    ['expected_hash'=>$expected_hash,'snapshot'=>$snapshot] = $context;
    if (!$snapshot['rendering_enabled'] || $snapshot['revision'] !== '1' || !is_array($snapshot['payload']) || !hash_equals($snapshot['payload_hash'], $expected_hash)) { return new WP_Error('atlas_disable_state_conflict', 'Exact enabled staged payload required.', ['status' => 409]); }
    delete_post_meta(8, '_atlas_metadata_enabled');
    update_option(ATLAS_METADATA_SAFETY_OPTION, ['activation_generation'=>$snapshot['activation_generation'],'enabled'=>false,'authorized_generation'=>'','plugin_version'=>ATLAS_METADATA_BRIDGE_VERSION,'plugin_checksum'=>atlas_metadata_plugin_checksum()], false);
    return rest_ensure_response(['status'=>'metadata_rendering_disabled','post_id'=>8,'payload_hash'=>$expected_hash,'revision'=>'1','rendering_enabled'=>false]);
}

function atlas_metadata_stage_rollback(WP_REST_Request $request) {
    $context = atlas_metadata_lifecycle_request($request); if (is_wp_error($context)) { return $context; }
    ['body'=>$body,'expected_hash'=>$expected_hash,'snapshot'=>$snapshot] = $context;
    if ($snapshot['rendering_enabled']) { return new WP_Error('atlas_rollback_rendering_enabled', 'Rendering must be disabled before payload rollback.', ['status' => 409]); }
    if ($snapshot['revision'] !== '1' || !is_array($snapshot['payload']) || !hash_equals($snapshot['payload_hash'], $expected_hash) || (string)($body['rollback_revision'] ?? '') !== '0') { return new WP_Error('atlas_rollback_state_conflict', 'Exact staged payload and rollback revision are required.', ['status' => 409]); }
    delete_post_meta(8, '_atlas_metadata_payload'); delete_post_meta(8, '_atlas_metadata_payload_hash'); delete_post_meta(8, '_atlas_metadata_revision'); delete_post_meta(8, '_atlas_metadata_enabled');
    return rest_ensure_response(['status'=>'metadata_payload_rolled_back','post_id'=>8,'payload_hash'=>'','revision'=>'0','rendering_enabled'=>false]);
}

function atlas_metadata_rollback(WP_REST_Request $request) {
    $body = $request->get_json_params(); $current = atlas_metadata_snapshot();
    if (!hash_equals($current['payload_hash'], (string) ($body['current_payload_hash'] ?? ''))) { return new WP_Error('atlas_rollback_conflict', 'Current payload hash changed.', ['status' => 409]); }
    if (!hash_equals($current['revision'], (string)($body['expected_revision'] ?? '')) || !hash_equals($current['activation_generation'], (string)($body['activation_generation'] ?? ''))) { return new WP_Error('atlas_rollback_state_conflict', 'Rollback state changed.', ['status' => 409]); }
    $snapshot = $body['snapshot'] ?? null; if (!is_array($snapshot)) { return new WP_Error('atlas_snapshot_missing', 'Rollback snapshot is required.', ['status' => 422]); }
    $current_hash = hash('sha256', wp_json_encode(atlas_metadata_canonicalize($current), JSON_UNESCAPED_SLASHES));
    $rollback_hash = hash('sha256', wp_json_encode(atlas_metadata_canonicalize($snapshot), JSON_UNESCAPED_SLASHES));
    if (!hash_equals($current_hash, (string)($body['expected_current_snapshot_hash'] ?? '')) || !hash_equals($rollback_hash, (string)($body['rollback_payload_hash'] ?? ''))) { return new WP_Error('atlas_rollback_snapshot_conflict', 'Rollback snapshot binding changed.', ['status' => 409]); }
    $revision = (string) (((int) $current['revision']) + 1);
    if (!empty($snapshot['rendering_enabled']) && is_array($snapshot['payload'])) {
        update_post_meta(8, '_atlas_metadata_payload', $snapshot['payload']); update_post_meta(8, '_atlas_metadata_payload_hash', (string) $snapshot['payload_hash']); update_post_meta(8, '_atlas_metadata_enabled', '1');
    } else {
        delete_post_meta(8, '_atlas_metadata_payload'); delete_post_meta(8, '_atlas_metadata_payload_hash'); delete_post_meta(8, '_atlas_metadata_enabled');
    }
    update_post_meta(8, '_atlas_metadata_revision', $revision);
    $safety = get_option(ATLAS_METADATA_SAFETY_OPTION, []); $generation = (string)($safety['activation_generation'] ?? '');
    update_option(ATLAS_METADATA_SAFETY_OPTION, ['activation_generation'=>$generation, 'enabled'=>false,
        'authorized_generation'=>'', 'plugin_version'=>ATLAS_METADATA_BRIDGE_VERSION,
        'plugin_checksum'=>atlas_metadata_plugin_checksum()], false);
    return rest_ensure_response(['status' => 'metadata_rolled_back', 'post_id' => 8, 'revision' => $revision, 'rendering_enabled' => !empty($snapshot['rendering_enabled'])]);
}

add_action('wp_head', function (): void {
    if (!is_page(8)) { return; }
    $snapshot = atlas_metadata_snapshot(); if (!$snapshot['rendering_enabled'] || !is_array($snapshot['payload'])
        || atlas_metadata_validate_payload($snapshot['payload'])
        || !hash_equals(atlas_metadata_hash($snapshot['payload']), $snapshot['payload_hash'])) { return; }
    $p = $snapshot['payload']; echo "\n<!-- Project Atlas Metadata Bridge v" . esc_html(ATLAS_METADATA_BRIDGE_VERSION) . " -->\n";
    echo '<meta name="description" content="' . esc_attr($p['meta_description']) . '">' . "\n";
    echo '<script type="application/ld+json" data-project-atlas="metadata">' . wp_json_encode($p['json_ld'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . '</script>' . "\n";
}, 20);
