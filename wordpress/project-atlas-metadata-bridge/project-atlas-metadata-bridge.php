<?php
/**
 * Plugin Name: Project Atlas Metadata Bridge
 * Description: Guarded Orlando-only metadata rendering bridge for Project Atlas.
 * Version: 0.57.4
 * Requires at least: 6.5
 * Requires PHP: 8.1
 * Author: Project Atlas
 */

if (!defined('ABSPATH')) { exit; }

define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.4');
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
    $image_url = 'https://www.drywoodtenting.com/wp-content/uploads/2026/07/orlando-drywood-termite-tenting-hero.png';
    $title = 'Drywood Termite Tenting in Orlando, FL';
    $description = 'Flo-Zone Pest And Termite Solutions Inc provides professional drywood termite tenting services for homes and properties in Orlando, Florida.';
    $organization = 'Flo-Zone Pest And Termite Solutions Inc';
    $image_id = $url . '#primaryimage';
    return ['schema_version'=>'1.0','page_id'=>41,'wordpress_post_id'=>8,'meta_description'=>$description,
        'open_graph'=>['og:title'=>$title,'og:description'=>$description,'og:image'=>$image_url,'og:url'=>$url,'og:type'=>'website'],
        'twitter'=>['twitter:card'=>'summary_large_image','twitter:title'=>$title,'twitter:description'=>$description,'twitter:image'=>$image_url],
        'json_ld'=>['@context'=>'https://schema.org','@graph'=>[
            ['@type'=>'WebSite','@id'=>'https://www.drywoodtenting.com/#website','url'=>'https://www.drywoodtenting.com/','name'=>$organization],
            ['@type'=>'Organization','@id'=>'https://www.drywoodtenting.com/#organization','name'=>$organization,'url'=>'https://www.drywoodtenting.com/','telephone'=>'(844) 600-8368','email'=>'Office@Flo-ZoneTenting.com','identifier'=>['@type'=>'PropertyValue','name'=>'License identifier','value'=>'JB360566']],
            ['@type'=>'Person','@id'=>'https://www.drywoodtenting.com/#jordan-ward','name'=>'Jordan Ward','jobTitle'=>'Certified Operator','worksFor'=>['@id'=>'https://www.drywoodtenting.com/#organization']],
            ['@type'=>'ImageObject','@id'=>$image_id,'url'=>$image_url,'contentUrl'=>$image_url,'caption'=>'Two-story Orlando Florida home professionally covered for drywood termite tenting'],
            ['@type'=>'Service','@id'=>$url.'#service','name'=>$title,'serviceType'=>'Drywood termite tenting','areaServed'=>['@type'=>'City','name'=>'Orlando','containedInPlace'=>['@type'=>'State','name'=>'Florida']],'provider'=>['@id'=>'https://www.drywoodtenting.com/#organization'],'image'=>['@id'=>$image_id]],
            ['@type'=>'WebPage','@id'=>$url.'#webpage','url'=>$url,'name'=>$title,'description'=>$description,'isPartOf'=>['@id'=>'https://www.drywoodtenting.com/#website'],'about'=>['@id'=>$url.'#service'],'primaryImageOfPage'=>['@id'=>$image_id]],
        ]], 'media_id'=>31, 'excluded_media_ids'=>[32]];
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
});

function atlas_metadata_apply(WP_REST_Request $request) {
    $body = $request->get_json_params(); $payload = $body['payload'] ?? null; $expected_hash = (string) ($body['payload_hash'] ?? '');
    $snapshot = atlas_metadata_snapshot(); $errors = atlas_metadata_validate_payload($payload);
    if ($errors) { return new WP_Error('atlas_invalid_payload', implode(' ', $errors), ['status' => 422]); }
    if (!hash_equals(atlas_metadata_hash($payload), $expected_hash)) { return new WP_Error('atlas_hash_mismatch', 'Payload hash mismatch.', ['status' => 409]); }
    if (!hash_equals($snapshot['revision'], (string) ($body['expected_revision'] ?? ''))) { return new WP_Error('atlas_revision_conflict', 'Metadata revision changed.', ['status' => 409]); }
    if (!hash_equals(hash('sha256', wp_json_encode(atlas_metadata_canonicalize($snapshot), JSON_UNESCAPED_SLASHES)), (string)($body['expected_snapshot_hash'] ?? ''))) { return new WP_Error('atlas_snapshot_conflict', 'Metadata snapshot changed.', ['status' => 409]); }
    if (!hash_equals($snapshot['activation_generation'], (string)($body['activation_generation'] ?? '')) || !hash_equals(atlas_metadata_plugin_checksum(), (string)($body['plugin_checksum'] ?? ''))) { return new WP_Error('atlas_activation_conflict', 'Activation generation or plugin checksum changed.', ['status' => 409]); }
    $post = get_post(8); if (!$post || $post->post_status !== 'publish' || $post->post_name !== 'drywood-termite-tenting-orlando-fl') { return new WP_Error('atlas_post_changed', 'Orlando post identity changed.', ['status' => 409]); }
    if ((int) get_post_thumbnail_id(8) !== 31 || get_post(31) === null || get_post(32) === null) { return new WP_Error('atlas_media_changed', 'Expected media state changed.', ['status' => 409]); }
    $revision = (string) (((int) $snapshot['revision']) + 1);
    update_post_meta(8, '_atlas_metadata_payload', $payload);
    update_post_meta(8, '_atlas_metadata_payload_hash', atlas_metadata_hash(atlas_metadata_approved_payload()));
    update_post_meta(8, '_atlas_metadata_revision', $revision);
    update_post_meta(8, '_atlas_metadata_enabled', '1');
    update_option(ATLAS_METADATA_SAFETY_OPTION, ['activation_generation'=>$snapshot['activation_generation'], 'enabled'=>true,
        'authorized_generation'=>$snapshot['activation_generation'], 'plugin_version'=>ATLAS_METADATA_BRIDGE_VERSION,
        'plugin_checksum'=>atlas_metadata_plugin_checksum()], false);
    return rest_ensure_response(['status' => 'metadata_applied', 'post_id' => 8, 'payload_hash' => $expected_hash, 'revision' => $revision, 'previous_snapshot' => $snapshot, 'rendering_enabled' => true]);
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
    foreach ($p['open_graph'] as $property => $content) { echo '<meta property="' . esc_attr($property) . '" content="' . esc_attr($content) . '">' . "\n"; }
    foreach ($p['twitter'] as $name => $content) { echo '<meta name="' . esc_attr($name) . '" content="' . esc_attr($content) . '">' . "\n"; }
    echo '<script type="application/ld+json" data-project-atlas="metadata">' . wp_json_encode($p['json_ld'], JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE) . '</script>' . "\n";
}, 20);
