<?php
/**
 * Local-only, Bridge-owned Performance Local V5 WordPress rehearsal renderer.
 */

if (!defined('ABSPATH')) { exit; }

define('ATLAS_PERFORMANCE_LOCAL_V5_META_KEY', '_project_atlas_performance_local_v5_v1');
define('ATLAS_PERFORMANCE_LOCAL_V5_SCHEMA', 'project-atlas-performance-local-v5-wordpress@1');
define('ATLAS_PERFORMANCE_LOCAL_V5_SPECIAL_MARKER', 'DEMO SPECIAL — NOT SITE CONTENT');
define('ATLAS_PERFORMANCE_LOCAL_V5_MAP_MARKER', 'DEMO MAP — NOT SITE CONTENT');
define('ATLAS_PERFORMANCE_LOCAL_V5_PLUGIN_FILE', dirname(__DIR__) . '/project-atlas-metadata-bridge.php');
define('ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE', dirname(__DIR__) . '/templates/performance-local-v5-page.php');
define('ATLAS_PERFORMANCE_LOCAL_V5_STYLESHEET', dirname(__DIR__) . '/assets/performance-local-v5.css');
define('ATLAS_PERFORMANCE_LOCAL_V5_SCRIPT', dirname(__DIR__) . '/assets/performance-local-v5.js');

function atlas_performance_local_v5_is_local_rehearsal(): bool {
    return function_exists('wp_get_environment_type') && wp_get_environment_type() === 'local';
}

function atlas_performance_local_v5_exact_record($value, array $expected_keys): bool {
    if (!is_array($value) || array_is_list($value)) { return false; }
    $actual = array_keys($value);
    sort($actual, SORT_STRING);
    sort($expected_keys, SORT_STRING);
    return $actual === $expected_keys;
}

function atlas_performance_local_v5_text($value, int $maximum = 4096): bool {
    return is_string($value)
        && $value !== ''
        && $value === trim($value)
        && strlen($value) <= $maximum
        && !preg_match('/[\x00-\x1F\x7F<>]/u', $value);
}

function atlas_performance_local_v5_optional_text($value, int $maximum = 4096): bool {
    return $value === null || atlas_performance_local_v5_text($value, $maximum);
}

function atlas_performance_local_v5_key($value): bool {
    return is_string($value) && preg_match('/^[a-z][a-z0-9_-]{0,119}$/', $value) === 1;
}

function atlas_performance_local_v5_sha256($value): bool {
    return is_string($value) && preg_match('/^[a-f0-9]{64}$/', $value) === 1;
}

function atlas_performance_local_v5_positive_integer($value): bool {
    return is_int($value) && $value > 0;
}

function atlas_performance_local_v5_finite_number($value): bool {
    return (is_int($value) || is_float($value)) && is_finite((float) $value);
}

function atlas_performance_local_v5_internal_href($value): bool {
    if (!atlas_performance_local_v5_text($value, 512) || str_contains($value, '\\') || str_contains($value, '%')) {
        return false;
    }
    if (str_starts_with($value, '#')) {
        return preg_match('/^#[A-Za-z][A-Za-z0-9_-]{0,119}$/', $value) === 1;
    }
    if (!str_starts_with($value, '/') || str_starts_with($value, '//') || str_contains($value, '?')) {
        return false;
    }
    $parts = explode('#', $value);
    if (count($parts) > 2 || ($parts[1] ?? '') !== '' && preg_match('/^[A-Za-z][A-Za-z0-9_-]{0,119}$/', $parts[1]) !== 1) {
        return false;
    }
    $path = $parts[0];
    if (preg_match('#^/[A-Za-z0-9._~/-]*$#', $path) !== 1) { return false; }
    foreach (explode('/', $path) as $segment) {
        if ($segment === '.' || $segment === '..') { return false; }
    }
    return true;
}

function atlas_performance_local_v5_tel_href($value): bool {
    return is_string($value) && preg_match('/^tel:\+[1-9][0-9]{7,14}$/', $value) === 1;
}

function atlas_performance_local_v5_asset_path($value): bool {
    if (!atlas_performance_local_v5_internal_href($value) || str_contains($value, '#')) { return false; }
    return preg_match('#^/wp-content/uploads/atlas-v5/[A-Za-z0-9][A-Za-z0-9._/-]*\.(?:avif|jpe?g|png|svg|webp)$#i', $value) === 1;
}

function atlas_performance_local_v5_image($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['src', 'alt'])) { return false; }
    return atlas_performance_local_v5_asset_path($value['src'])
        && atlas_performance_local_v5_text($value['alt'], 320);
}

function atlas_performance_local_v5_media($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['src', 'alt', 'title', 'focal_x', 'focal_y'])) { return false; }
    return atlas_performance_local_v5_asset_path($value['src'])
        && atlas_performance_local_v5_text($value['alt'], 320)
        && atlas_performance_local_v5_optional_text($value['title'], 320)
        && atlas_performance_local_v5_finite_number($value['focal_x'])
        && (float) $value['focal_x'] >= 0.0
        && (float) $value['focal_x'] <= 1.0
        && atlas_performance_local_v5_finite_number($value['focal_y'])
        && (float) $value['focal_y'] >= 0.0
        && (float) $value['focal_y'] <= 1.0;
}

function atlas_performance_local_v5_payload_identity($value): bool {
    if (!atlas_performance_local_v5_exact_record(
        $value,
        ['fixture_key', 'source_page', 'source_composition', 'source_hash', 'frozen_inputs']
    )) { return false; }
    if (!in_array($value['fixture_key'], [
        'city_service', 'estimate', 'special_demo', 'optional_modules', 'business_location',
        'valid_sixth_field', 'invalid_extra_field',
    ], true)) { return false; }
    if (!is_string($value['source_page']) || preg_match('/^generated-page:[1-9][0-9]*$/', $value['source_page']) !== 1) { return false; }
    if (!is_string($value['source_composition']) || preg_match('/^composition:[1-9][0-9]*:v[1-9][0-9]*$/', $value['source_composition']) !== 1) { return false; }
    if (!atlas_performance_local_v5_sha256($value['source_hash'])) { return false; }
    if (!is_array($value['frozen_inputs']) || !array_is_list($value['frozen_inputs'])
        || count($value['frozen_inputs']) < 1 || count($value['frozen_inputs']) > 256) { return false; }
    $seen = [];
    foreach ($value['frozen_inputs'] as $input) {
        if (!atlas_performance_local_v5_exact_record($input, ['path', 'sha256'])
            || !atlas_performance_local_v5_text($input['path'], 512)
            || str_starts_with($input['path'], '/')
            || str_contains($input['path'], '\\')
            || preg_match('#(^|/)\.\.?(/|$)#', $input['path'])
            || !atlas_performance_local_v5_sha256($input['sha256'])
            || isset($seen[$input['path']])) { return false; }
        $seen[$input['path']] = true;
    }
    return true;
}

function atlas_performance_local_v5_website($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, [
        'identity', 'display_name', 'company_name', 'tagline', 'phone_display',
        'phone_href', 'contact_email', 'header_logo', 'footer_logo',
    ])) { return false; }
    return atlas_performance_local_v5_text($value['identity'], 240)
        && atlas_performance_local_v5_text($value['display_name'], 240)
        && atlas_performance_local_v5_text($value['company_name'], 240)
        && atlas_performance_local_v5_text($value['tagline'], 320)
        && atlas_performance_local_v5_text($value['phone_display'], 80)
        && atlas_performance_local_v5_tel_href($value['phone_href'])
        && atlas_performance_local_v5_text($value['contact_email'], 254)
        && filter_var($value['contact_email'], FILTER_VALIDATE_EMAIL) !== false
        && atlas_performance_local_v5_image($value['header_logo'])
        && atlas_performance_local_v5_image($value['footer_logo']);
}

function atlas_performance_local_v5_navigation_item($value): bool {
    return atlas_performance_local_v5_exact_record($value, ['label', 'href', 'parent_label'])
        && atlas_performance_local_v5_text($value['label'], 160)
        && atlas_performance_local_v5_internal_href($value['href'])
        && atlas_performance_local_v5_optional_text($value['parent_label'], 160);
}

function atlas_performance_local_v5_navigation($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['utility', 'primary', 'mobile_label'])
        || !atlas_performance_local_v5_text($value['mobile_label'], 120)) { return false; }
    foreach (['utility', 'primary'] as $group) {
        if (!is_array($value[$group]) || !array_is_list($value[$group]) || count($value[$group]) > 48) { return false; }
        foreach ($value[$group] as $item) {
            if (!atlas_performance_local_v5_navigation_item($item)) { return false; }
        }
    }
    if (count($value['primary']) < 1) { return false; }
    $parent_labels = [];
    foreach ($value['primary'] as $item) {
        if ($item['parent_label'] === null) { $parent_labels[$item['label']] = true; }
    }
    foreach ($value['primary'] as $item) {
        if ($item['parent_label'] !== null && !isset($parent_labels[$item['parent_label']])) { return false; }
    }
    foreach ($value['utility'] as $item) {
        if ($item['parent_label'] !== null) { return false; }
    }
    return true;
}

function atlas_performance_local_v5_page($value): bool {
    if (!atlas_performance_local_v5_exact_record(
        $value,
        ['page_type', 'title', 'slug', 'meta_title', 'meta_description', 'h1']
    )) { return false; }
    return atlas_performance_local_v5_key($value['page_type'])
        && atlas_performance_local_v5_text($value['title'], 320)
        && is_string($value['slug'])
        && preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $value['slug']) === 1
        && atlas_performance_local_v5_text($value['meta_title'], 320)
        && atlas_performance_local_v5_text($value['meta_description'], 1000)
        && atlas_performance_local_v5_text($value['h1'], 320);
}

function atlas_performance_local_v5_action($value, array $modes, bool $telephone = false): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['mode', 'label', 'href'])
        || !in_array($value['mode'], $modes, true)
        || !atlas_performance_local_v5_text($value['label'], 160)) { return false; }
    return $telephone
        ? atlas_performance_local_v5_tel_href($value['href'])
        : atlas_performance_local_v5_internal_href($value['href']);
}

function atlas_performance_local_v5_sticky_action($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['phone', 'action'])
        || !atlas_performance_local_v5_exact_record($value['phone'], ['label', 'href'])
        || !atlas_performance_local_v5_text($value['phone']['label'], 160)
        || !atlas_performance_local_v5_tel_href($value['phone']['href'])) { return false; }
    return $value['action'] === null || atlas_performance_local_v5_action(
        $value['action'],
        ['estimate', 'service_promotion', 'special']
    );
}

function atlas_performance_local_v5_hero($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, [
        'eyebrow', 'h1', 'introduction', 'media', 'call_action', 'estimate_action',
    ])) { return false; }
    return atlas_performance_local_v5_text($value['eyebrow'], 160)
        && atlas_performance_local_v5_text($value['h1'], 320)
        && atlas_performance_local_v5_text($value['introduction'], 4000)
        && atlas_performance_local_v5_media($value['media'])
        && atlas_performance_local_v5_exact_record($value['call_action'], ['label', 'href'])
        && atlas_performance_local_v5_text($value['call_action']['label'], 160)
        && atlas_performance_local_v5_tel_href($value['call_action']['href'])
        && atlas_performance_local_v5_exact_record($value['estimate_action'], ['label', 'href'])
        && atlas_performance_local_v5_text($value['estimate_action']['label'], 160)
        && atlas_performance_local_v5_internal_href($value['estimate_action']['href']);
}

function atlas_performance_local_v5_sections($value): bool {
    if (!is_array($value) || !array_is_list($value) || count($value) > 32) { return false; }
    $seen = [];
    foreach ($value as $section) {
        if (!atlas_performance_local_v5_exact_record($section, ['key', 'heading', 'body', 'media'])
            || !atlas_performance_local_v5_key($section['key'])
            || !atlas_performance_local_v5_text($section['heading'], 320)
            || !atlas_performance_local_v5_text($section['body'], 10000)
            || ($section['media'] !== null && !atlas_performance_local_v5_media($section['media']))
            || isset($seen[$section['key']])) { return false; }
        $seen[$section['key']] = true;
    }
    return true;
}

function atlas_performance_local_v5_related_pages($value): bool {
    if (!is_array($value) || !array_is_list($value) || count($value) > 48) { return false; }
    $seen = [];
    foreach ($value as $item) {
        if (!atlas_performance_local_v5_exact_record($item, ['label', 'href', 'relationship_type'])
            || !atlas_performance_local_v5_text($item['label'], 240)
            || !atlas_performance_local_v5_internal_href($item['href'])
            || !atlas_performance_local_v5_key($item['relationship_type'])
            || isset($seen[$item['href']])) { return false; }
        $seen[$item['href']] = true;
    }
    return true;
}

function atlas_performance_local_v5_faq($value): bool {
    if (!is_array($value) || !array_is_list($value) || count($value) > 32) { return false; }
    foreach ($value as $item) {
        if (!atlas_performance_local_v5_exact_record($item, ['question', 'answer'])
            || !atlas_performance_local_v5_text($item['question'], 500)
            || !atlas_performance_local_v5_text($item['answer'], 8000)) { return false; }
    }
    return true;
}

function atlas_performance_local_v5_review_trust($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['heading', 'presentation', 'sources'])
        || !atlas_performance_local_v5_text($value['heading'], 320)
        || $value['presentation'] !== 'local_rehearsal'
        || !is_array($value['sources']) || !array_is_list($value['sources'])
        || count($value['sources']) < 1 || count($value['sources']) > 3) { return false; }
    $seen = [];
    foreach ($value['sources'] as $source) {
        if (!atlas_performance_local_v5_exact_record($source, [
            'source_key', 'public_name', 'description', 'badge', 'profile_href',
            'rating_text', 'review_count_text',
        ])
            || !atlas_performance_local_v5_key($source['source_key'])
            || !atlas_performance_local_v5_text($source['public_name'], 240)
            || !atlas_performance_local_v5_text($source['description'], 2000)
            || !atlas_performance_local_v5_image($source['badge'])
            || ($source['profile_href'] !== null && !atlas_performance_local_v5_internal_href($source['profile_href']))
            || !atlas_performance_local_v5_optional_text($source['rating_text'], 160)
            || !atlas_performance_local_v5_optional_text($source['review_count_text'], 160)
            || isset($seen[$source['source_key']])) { return false; }
        $seen[$source['source_key']] = true;
    }
    return true;
}

function atlas_performance_local_v5_location_map($value): bool {
    if (!is_array($value) || array_is_list($value)) { return false; }
    if (($value['mode'] ?? null) === 'city_service_area') {
        if (!atlas_performance_local_v5_exact_record($value, [
            'mode', 'heading', 'description', 'target_city', 'target_state', 'map_title',
            'embed_src', 'demo_label', 'presentation',
        ])) { return false; }
        return atlas_performance_local_v5_text($value['heading'], 320)
            && atlas_performance_local_v5_text($value['description'], 2000)
            && atlas_performance_local_v5_text($value['target_city'], 120)
            && atlas_performance_local_v5_text($value['target_state'], 120)
            && atlas_performance_local_v5_text($value['map_title'], 320)
            && $value['embed_src'] === null
            && $value['demo_label'] === ATLAS_PERFORMANCE_LOCAL_V5_MAP_MARKER
            && $value['presentation'] === 'local_rehearsal';
    }
    if (($value['mode'] ?? null) !== 'business_location'
        || !atlas_performance_local_v5_exact_record($value, [
            'mode', 'heading', 'approved_location_name', 'address_lines', 'description',
            'phone_action', 'directions_action', 'map_title', 'embed_src', 'demo_label',
            'presentation',
        ])
        || !atlas_performance_local_v5_text($value['heading'], 320)
        || !atlas_performance_local_v5_text($value['approved_location_name'], 320)
        || !is_array($value['address_lines']) || !array_is_list($value['address_lines'])
        || count($value['address_lines']) < 1 || count($value['address_lines']) > 4
        || !atlas_performance_local_v5_optional_text($value['description'], 2000)
        || !atlas_performance_local_v5_text($value['map_title'], 320)
        || $value['embed_src'] !== null
        || $value['demo_label'] !== ATLAS_PERFORMANCE_LOCAL_V5_MAP_MARKER
        || $value['presentation'] !== 'local_rehearsal') { return false; }
    foreach ($value['address_lines'] as $line) {
        if (!atlas_performance_local_v5_text($line, 240)) { return false; }
    }
    if ($value['phone_action'] !== null
        && (!atlas_performance_local_v5_exact_record($value['phone_action'], ['label', 'href'])
            || !atlas_performance_local_v5_text($value['phone_action']['label'], 160)
            || !atlas_performance_local_v5_tel_href($value['phone_action']['href']))) { return false; }
    if ($value['directions_action'] !== null
        && (!atlas_performance_local_v5_exact_record($value['directions_action'], ['label', 'href'])
            || !atlas_performance_local_v5_text($value['directions_action']['label'], 160)
            || !atlas_performance_local_v5_internal_href($value['directions_action']['href']))) { return false; }
    return true;
}

function atlas_performance_local_v5_optional_modules($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['review_trust', 'location_map'])) { return false; }
    return ($value['review_trust'] === null || atlas_performance_local_v5_review_trust($value['review_trust']))
        && ($value['location_map'] === null || atlas_performance_local_v5_location_map($value['location_map']));
}

function atlas_performance_local_v5_form_field($field, int $index): bool {
    if (!atlas_performance_local_v5_exact_record($field, [
        'field_key', 'label', 'required', 'control', 'input_type', 'order',
        'maximum_length', 'validation',
    ])
        || !atlas_performance_local_v5_key($field['field_key'])
        || !atlas_performance_local_v5_text($field['label'], 160)
        || !is_bool($field['required'])
        || !in_array($field['control'], ['input', 'textarea'], true)
        || !in_array($field['input_type'], ['text', 'tel', 'email'], true)
        || $field['order'] !== $index + 1
        || !is_int($field['maximum_length'])
        || $field['maximum_length'] < 1
        || $field['maximum_length'] > 5000
        || !atlas_performance_local_v5_exact_record($field['validation'], ['rule', 'minimum_length', 'maximum_length'])
        || !in_array($field['validation']['rule'], ['nonempty_text', 'phone', 'postal_code', 'free_text', 'email_address'], true)
        || !is_int($field['validation']['minimum_length'])
        || $field['validation']['minimum_length'] < 0
        || $field['validation']['maximum_length'] !== $field['maximum_length']
        || $field['validation']['minimum_length'] > $field['maximum_length']) { return false; }
    if ($field['control'] === 'textarea' && $field['input_type'] !== 'text') { return false; }
    if ($index < 5) {
        $expected = [
            ['name', 'Name', true, 'input', 'text'],
            ['phone', 'Phone', true, 'input', 'tel'],
            ['postal-code', 'ZIP code', true, 'input', 'text'],
            ['requested-service', 'Requested service', true, 'input', 'text'],
            ['message', 'Optional message', false, 'textarea', 'text'],
        ][$index];
        return [$field['field_key'], $field['label'], $field['required'], $field['control'], $field['input_type']] === $expected;
    }
    return !in_array($field['field_key'], ['name', 'phone', 'postal-code', 'requested-service', 'message'], true);
}

function atlas_performance_local_v5_form($value): bool {
    if (!atlas_performance_local_v5_exact_record(
        $value,
        ['state', 'anchor', 'submit_label', 'notice', 'fields']
    )
        || $value['state'] !== 'disabled'
        || $value['anchor'] !== 'estimate-form'
        || !atlas_performance_local_v5_text($value['submit_label'], 160)
        || !atlas_performance_local_v5_text($value['notice'], 1000)
        || !is_array($value['fields']) || !array_is_list($value['fields'])
        || !in_array(count($value['fields']), [5, 6], true)) { return false; }
    $seen = [];
    foreach ($value['fields'] as $index => $field) {
        if (!atlas_performance_local_v5_form_field($field, $index) || isset($seen[$field['field_key']])) { return false; }
        $seen[$field['field_key']] = true;
    }
    return true;
}

function atlas_performance_local_v5_conditional($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['estimate', 'special'])) { return false; }
    if ($value['estimate'] !== null) {
        if (!atlas_performance_local_v5_exact_record(
            $value['estimate'],
            ['heading', 'introduction', 'phone_alternative_enabled']
        )
            || !atlas_performance_local_v5_text($value['estimate']['heading'], 320)
            || !atlas_performance_local_v5_text($value['estimate']['introduction'], 4000)
            || !is_bool($value['estimate']['phone_alternative_enabled'])) { return false; }
    }
    if ($value['special'] !== null) {
        if (!atlas_performance_local_v5_exact_record($value['special'], [
            'headline', 'description', 'terms', 'call_action_enabled',
            'estimate_action_enabled', 'demo_label',
        ])
            || !atlas_performance_local_v5_text($value['special']['headline'], 320)
            || !atlas_performance_local_v5_text($value['special']['description'], 4000)
            || !atlas_performance_local_v5_optional_text($value['special']['terms'], 4000)
            || !is_bool($value['special']['call_action_enabled'])
            || !is_bool($value['special']['estimate_action_enabled'])
            || $value['special']['headline'] !== ATLAS_PERFORMANCE_LOCAL_V5_SPECIAL_MARKER
            || $value['special']['demo_label'] !== ATLAS_PERFORMANCE_LOCAL_V5_SPECIAL_MARKER) { return false; }
    }
    return true;
}

function atlas_performance_local_v5_footer($value): bool {
    if (!atlas_performance_local_v5_exact_record(
        $value,
        ['navigation', 'company_name', 'phone_display', 'contact_email', 'logo']
    )
        || !is_array($value['navigation']) || !array_is_list($value['navigation'])
        || count($value['navigation']) > 48
        || !atlas_performance_local_v5_text($value['company_name'], 240)
        || !atlas_performance_local_v5_text($value['phone_display'], 80)
        || !atlas_performance_local_v5_text($value['contact_email'], 254)
        || filter_var($value['contact_email'], FILTER_VALIDATE_EMAIL) === false
        || !atlas_performance_local_v5_image($value['logo'])) { return false; }
    foreach ($value['navigation'] as $item) {
        if (!atlas_performance_local_v5_exact_record($item, ['label', 'href'])
            || !atlas_performance_local_v5_text($item['label'], 160)
            || !atlas_performance_local_v5_internal_href($item['href'])) { return false; }
    }
    return true;
}

function atlas_performance_local_v5_token_graph($value, int $depth = 0): bool {
    if ($depth > 12 || !is_array($value) || array_is_list($value) || !$value || count($value) > 128) { return false; }
    foreach ($value as $key => $child) {
        if (!is_string($key) || preg_match('/^[a-z][a-z0-9_]{0,79}$/', $key) !== 1) { return false; }
        if (is_array($child)) {
            if (!atlas_performance_local_v5_token_graph($child, $depth + 1)) { return false; }
        } elseif (is_string($child)) {
            if (!atlas_performance_local_v5_text($child, 2048)) { return false; }
        } elseif (is_int($child) || is_float($child)) {
            if (!is_finite((float) $child)) { return false; }
        } elseif (!is_bool($child)) {
            return false;
        }
    }
    return true;
}

function atlas_performance_local_v5_theme($value): bool {
    if (!atlas_performance_local_v5_exact_record($value, ['family', 'version', 'source_theme', 'tokens'])
        || $value['family'] !== 'performance-local'
        || $value['version'] !== 5
        || !atlas_performance_local_v5_exact_record(
            $value['source_theme'],
            ['key', 'version', 'token_contract_version', 'token_hash_sha256']
        )
        || !atlas_performance_local_v5_text($value['source_theme']['key'], 160)
        || !atlas_performance_local_v5_positive_integer($value['source_theme']['version'])
        || !atlas_performance_local_v5_positive_integer($value['source_theme']['token_contract_version'])
        || !atlas_performance_local_v5_sha256($value['source_theme']['token_hash_sha256'])
        || !atlas_performance_local_v5_exact_record($value['tokens'], [
            'colors', 'typography', 'spacing', 'content_widths', 'borders', 'shadows',
            'buttons', 'cards', 'navigation', 'cta', 'responsive', 'layout', 'motion',
        ])) { return false; }
    return atlas_performance_local_v5_token_graph($value['tokens']);
}

function atlas_performance_local_v5_validate_payload($payload): array {
    $errors = [];
    $top_level = [
        'schema_version', 'surface', 'rehearsal_only', 'payload_identity', 'website',
        'navigation', 'page', 'sticky_action', 'hero', 'sections', 'related_pages',
        'faq', 'optional_modules', 'form', 'conditional', 'footer', 'theme',
    ];
    if (!atlas_performance_local_v5_is_local_rehearsal()) { $errors[] = 'WordPress environment is not local.'; }
    if (!atlas_performance_local_v5_exact_record($payload, $top_level)) {
        return array_merge($errors, ['Payload keys differ from the exact V5 rehearsal contract.']);
    }
    if ($payload['schema_version'] !== ATLAS_PERFORMANCE_LOCAL_V5_SCHEMA) { $errors[] = 'Schema identity differs.'; }
    if (!in_array($payload['surface'], ['city_service', 'estimate', 'special_demo'], true)) { $errors[] = 'Surface is unsupported.'; }
    if ($payload['rehearsal_only'] !== true) { $errors[] = 'Payload is not rehearsal-only.'; }
    if (!atlas_performance_local_v5_payload_identity($payload['payload_identity'])) { $errors[] = 'Payload identity is invalid.'; }
    if (!atlas_performance_local_v5_website($payload['website'])) { $errors[] = 'Website contract is invalid.'; }
    if (!atlas_performance_local_v5_navigation($payload['navigation'])) { $errors[] = 'Navigation contract is invalid.'; }
    if (!atlas_performance_local_v5_page($payload['page'])) { $errors[] = 'Page contract is invalid.'; }
    if (!atlas_performance_local_v5_sticky_action($payload['sticky_action'])) { $errors[] = 'Sticky action contract is invalid.'; }
    if (($payload['hero'] !== null && !atlas_performance_local_v5_hero($payload['hero']))
        || ($payload['surface'] === 'city_service' && $payload['hero'] === null)
        || ($payload['surface'] !== 'city_service' && $payload['hero'] !== null)) { $errors[] = 'Hero contract is invalid for the surface.'; }
    if (!atlas_performance_local_v5_sections($payload['sections'])) { $errors[] = 'Section contract is invalid.'; }
    if (!atlas_performance_local_v5_related_pages($payload['related_pages'])) { $errors[] = 'Related-page contract is invalid.'; }
    if (!atlas_performance_local_v5_faq($payload['faq'])) { $errors[] = 'FAQ contract is invalid.'; }
    if ($payload['surface'] === 'city_service' && (!$payload['sections'] || !$payload['faq'])) {
        $errors[] = 'City-service surface requires governed sections and FAQ items.';
    }
    if ($payload['surface'] === 'city_service') {
        $final_conversion_count = 0;
        if (is_array($payload['sections']) && array_is_list($payload['sections'])) {
            foreach ($payload['sections'] as $section) {
                if (is_array($section) && ($section['key'] ?? null) === 'final_conversion') {
                    $final_conversion_count++;
                    if (($section['media'] ?? null) !== null) { $errors[] = 'Final conversion cannot contain detached media.'; }
                }
            }
        }
        if ($final_conversion_count !== 1) { $errors[] = 'City-service surface requires one exact final conversion section.'; }
    }
    if (!atlas_performance_local_v5_optional_modules($payload['optional_modules'])) { $errors[] = 'Optional-module contract is invalid.'; }
    if (!atlas_performance_local_v5_form($payload['form'])) { $errors[] = 'Disabled form contract is invalid.'; }
    if (!atlas_performance_local_v5_conditional($payload['conditional'])) { $errors[] = 'Conditional-page contract is invalid.'; }
    if ($payload['surface'] === 'estimate' && $payload['conditional']['estimate'] === null) { $errors[] = 'Estimate surface lacks its conditional contract.'; }
    if ($payload['surface'] === 'special_demo' && $payload['conditional']['special'] === null) { $errors[] = 'Special surface lacks its conditional contract.'; }
    if (!atlas_performance_local_v5_footer($payload['footer'])) { $errors[] = 'Footer contract is invalid.'; }
    if (!atlas_performance_local_v5_theme($payload['theme'])) { $errors[] = 'Theme contract is invalid.'; }

    if (!$errors) {
        if ($payload['sticky_action']['phone']['href'] !== $payload['website']['phone_href']
            || $payload['footer']['phone_display'] !== $payload['website']['phone_display']
            || $payload['footer']['contact_email'] !== $payload['website']['contact_email']
            || $payload['footer']['company_name'] !== $payload['website']['company_name']) {
            $errors[] = 'Governed website contact identity is inconsistent.';
        }
        if ($payload['hero'] !== null
            && ($payload['hero']['h1'] !== $payload['page']['h1']
                || $payload['hero']['call_action']['href'] !== $payload['website']['phone_href'])) {
            $errors[] = 'Hero identity is inconsistent.';
        }
        $location = $payload['optional_modules']['location_map'];
        if ($location !== null && $location['mode'] === 'business_location'
            && $location['phone_action'] !== null
            && $location['phone_action']['href'] !== $payload['website']['phone_href']) {
            $errors[] = 'Business-location phone action differs from the governed website phone.';
        }
    }
    return $errors;
}

function atlas_performance_local_v5_payload_is_valid($payload): bool {
    return atlas_performance_local_v5_validate_payload($payload) === [];
}

function atlas_performance_local_v5_register_meta(): void {
    if (!atlas_performance_local_v5_is_local_rehearsal()) { return; }
    register_post_meta('page', ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, [
        'type' => 'object',
        'single' => true,
        'show_in_rest' => false,
        'default' => [],
        'sanitize_callback' => function ($value) {
            return atlas_performance_local_v5_payload_is_valid($value) ? $value : [];
        },
        'auth_callback' => function (): bool {
            return current_user_can('edit_pages');
        },
    ]);
}
add_action('init', 'atlas_performance_local_v5_register_meta');

function atlas_performance_local_v5_public_page_request(): bool {
    return atlas_performance_local_v5_is_local_rehearsal()
        && !is_admin()
        && !wp_doing_ajax()
        && !wp_doing_cron()
        && !(defined('REST_REQUEST') && REST_REQUEST)
        && !(defined('WP_CLI') && WP_CLI)
        && !is_feed()
        && !is_search()
        && !is_archive()
        && !is_preview()
        && is_singular('page');
}

function atlas_performance_local_v5_runtime_files(): array {
    return [
        ATLAS_PERFORMANCE_LOCAL_V5_PLUGIN_FILE,
        __FILE__,
        ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE,
        ATLAS_PERFORMANCE_LOCAL_V5_STYLESHEET,
        ATLAS_PERFORMANCE_LOCAL_V5_SCRIPT,
    ];
}

function atlas_performance_local_v5_runtime_checksum(): string {
    $bound = '';
    foreach (atlas_performance_local_v5_runtime_files() as $file) {
        if (!is_file($file)) { return ''; }
        $bound .= basename($file) . ':' . hash_file('sha256', $file) . "\n";
    }
    return hash('sha256', $bound);
}

function atlas_performance_local_v5_current_payload(): ?array {
    if (!atlas_performance_local_v5_public_page_request()
        || atlas_performance_local_v5_runtime_checksum() === '') { return null; }
    $post_id = get_queried_object_id();
    if (!is_int($post_id) || $post_id < 1) { return null; }
    $post = get_post($post_id);
    if (!$post || $post->post_type !== 'page' || $post->post_status !== 'publish') { return null; }
    $payload = get_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, true);
    return atlas_performance_local_v5_payload_is_valid($payload) ? $payload : null;
}

function atlas_performance_local_v5_template_include(string $template): string {
    return atlas_performance_local_v5_current_payload() === null
        ? $template
        : ATLAS_PERFORMANCE_LOCAL_V5_TEMPLATE;
}
add_filter('template_include', 'atlas_performance_local_v5_template_include', 99);

function atlas_performance_local_v5_enqueue_assets(): void {
    if (atlas_performance_local_v5_current_payload() === null) { return; }
    $base_url = plugin_dir_url(ATLAS_PERFORMANCE_LOCAL_V5_PLUGIN_FILE);
    wp_enqueue_style(
        'project-atlas-performance-local-v5',
        $base_url . 'assets/performance-local-v5.css',
        [],
        hash_file('sha256', ATLAS_PERFORMANCE_LOCAL_V5_STYLESHEET)
    );
    wp_enqueue_script(
        'project-atlas-performance-local-v5',
        $base_url . 'assets/performance-local-v5.js',
        [],
        hash_file('sha256', ATLAS_PERFORMANCE_LOCAL_V5_SCRIPT),
        true
    );
    wp_script_add_data('project-atlas-performance-local-v5', 'strategy', 'defer');
}
add_action('wp_enqueue_scripts', 'atlas_performance_local_v5_enqueue_assets');

function atlas_performance_local_v5_root_style(array $theme): string {
    $declarations = [];
    foreach ($theme['tokens']['colors'] as $name => $value) {
        if (!is_string($name) || preg_match('/^[a-z][a-z0-9_]{0,79}$/', $name) !== 1
            || !is_string($value) || preg_match('/^#[0-9A-Fa-f]{3,8}$/', $value) !== 1) { continue; }
        $declarations[] = '--atlas-color-' . str_replace('_', '-', $name) . ':' . $value;
    }
    return implode(';', $declarations);
}

function atlas_performance_local_v5_render_top_stack(array $payload): void {
    $phone = $payload['sticky_action']['phone'];
    $action = $payload['sticky_action']['action'];
    ?>
    <div
        class="performanceLocalV5TopConversionStack"
        data-v5-top-conversion-stack="true"
        data-v5-top-action-mode="<?php echo esc_attr($action === null ? 'disabled' : $action['mode']); ?>"
        data-v5-top-action-enabled="<?php echo $action === null ? 'false' : 'true'; ?>"
    >
        <div class="performanceLocalV5StickyPhoneBar">
            <a href="<?php echo esc_url($phone['href']); ?>" aria-label="<?php echo esc_attr($phone['label'] . ' ' . $payload['website']['phone_display']); ?>">
                <span><?php echo esc_html($phone['label']); ?> <strong><?php echo esc_html($payload['website']['phone_display']); ?></strong></span>
            </a>
        </div>
        <?php if ($action !== null): ?>
            <aside class="performanceLocalV5StickyActionBanner" aria-label="<?php echo esc_attr($action['label']); ?>">
                <a href="<?php echo esc_url($action['href']); ?>"><?php echo esc_html($action['label']); ?></a>
            </aside>
        <?php endif; ?>
    </div>
    <?php
}

function atlas_performance_local_v5_navigation_tree(array $navigation): array {
    $roots = [];
    $primary_hrefs = [];
    foreach ($navigation['primary'] as $item) { $primary_hrefs[$item['href']] = true; }
    foreach ($navigation['primary'] as $item) {
        if ($item['parent_label'] === null) {
            $item['children'] = [];
            $roots[$item['label']] = $item;
        }
    }
    foreach ($navigation['primary'] as $item) {
        if ($item['parent_label'] !== null) { $roots[$item['parent_label']]['children'][] = $item; }
    }
    foreach ($navigation['utility'] as $item) {
        if (isset($primary_hrefs[$item['href']])) { continue; }
        $item['children'] = [];
        $roots['utility:' . $item['label']] = $item;
    }
    return array_values($roots);
}

function atlas_performance_local_v5_render_navigation_list(array $tree, string $id_prefix, string $list_class = ''): void {
    echo '<ul' . ($list_class !== '' ? ' class="' . esc_attr($list_class) . '"' : '') . '>';
    foreach ($tree as $index => $item) {
        $submenu_id = $id_prefix . '-submenu-' . ($index + 1);
        echo '<li><div class="performanceLocalDrawerRow">';
        echo '<a href="' . esc_url($item['href']) . '">' . esc_html($item['label']) . '</a>';
        if ($item['children']) {
            echo '<button type="button" data-atlas-v5-submenu-toggle aria-expanded="false" aria-controls="' . esc_attr($submenu_id) . '" aria-label="' . esc_attr('Toggle ' . $item['label'] . ' submenu') . '"><span aria-hidden="true">⌄</span></button>';
        }
        echo '</div>';
        if ($item['children']) {
            echo '<ul id="' . esc_attr($submenu_id) . '" class="performanceLocalDropdown" hidden>';
            foreach ($item['children'] as $child) {
                echo '<li><a href="' . esc_url($child['href']) . '">' . esc_html($child['label']) . '</a></li>';
            }
            echo '</ul>';
        }
        echo '</li>';
    }
    echo '</ul>';
}

function atlas_performance_local_v5_render_mobile_menu_trigger(array $payload, bool $legacy): void {
    $trigger_class = $legacy ? 'performanceLocalMenuTrigger' : 'performanceLocalV5MenuTrigger';
    ?>
    <?php if ($legacy): ?><div class="performanceLocalMobileNavigation"><?php endif; ?>
        <button
            class="<?php echo esc_attr($trigger_class); ?>"
            type="button"
            data-atlas-v5-menu-toggle
            aria-controls="atlas-performance-local-v5-mobile-menu"
            aria-expanded="false"
            aria-label="<?php echo esc_attr($payload['navigation']['mobile_label']); ?>"
        ><span aria-hidden="true">☰</span></button>
    <?php if ($legacy): ?></div><?php endif; ?>
    <?php
}

function atlas_performance_local_v5_render_mobile_drawer(array $website, array $tree, bool $legacy): void {
    $backdrop_class = $legacy ? 'performanceLocalDrawerBackdrop' : 'performanceLocalV5DrawerBackdrop';
    $drawer_class = $legacy ? 'performanceLocalDrawer' : 'performanceLocalV5Drawer';
    ?>
    <div class="<?php echo esc_attr($backdrop_class); ?>" data-atlas-v5-menu-backdrop hidden>
        <div
            id="atlas-performance-local-v5-mobile-menu"
            class="<?php echo esc_attr($drawer_class); ?>"
            data-atlas-v5-mobile-nav
            role="dialog"
            aria-modal="true"
            aria-label="Website navigation"
            hidden
        >
            <?php if ($legacy): ?>
                <div class="performanceLocalDrawerHeader">
                    <strong><?php echo esc_html($website['display_name']); ?></strong>
                    <button type="button" data-atlas-v5-menu-close aria-label="Close website navigation">×</button>
                </div>
            <?php else: ?>
                <button type="button" data-atlas-v5-menu-close aria-label="Close website navigation">×</button>
            <?php endif; ?>
            <nav aria-label="Mobile website navigation">
                <?php atlas_performance_local_v5_render_navigation_list($tree, 'atlas-v5-mobile', 'performanceLocalDrawerList'); ?>
            </nav>
        </div>
    </div>
    <?php
}

function atlas_performance_local_v5_render_header(array $payload, bool $legacy): void {
    $website = $payload['website'];
    $tree = atlas_performance_local_v5_navigation_tree($payload['navigation']);
    $header_class = $legacy ? 'performanceLocalHeader' : 'performanceLocalV5Header';
    $container_class = $legacy
        ? 'performanceLocalContainer performanceLocalHeaderInner'
        : 'performanceLocalV5Container performanceLocalV5HeaderInner';
    $brand_class = $legacy ? 'performanceLocalBrand' : 'performanceLocalV5Brand';
    $desktop_class = $legacy ? 'performanceLocalDesktopNavigation' : 'performanceLocalV5DesktopNav';
    ?>
    <header class="<?php echo esc_attr($header_class); ?>" data-v5-menu-open="false">
        <div class="<?php echo esc_attr($container_class); ?>">
            <a class="<?php echo esc_attr($brand_class); ?>" href="/" aria-label="<?php echo esc_attr($website['display_name'] . ' home'); ?>">
                <img class="previewBrandLogo" src="<?php echo esc_url($website['header_logo']['src']); ?>" alt="<?php echo esc_attr($website['header_logo']['alt']); ?>" decoding="async">
                <span class="performanceLocalBrandText"><strong><?php echo esc_html($website['display_name']); ?></strong><small><?php echo esc_html($website['tagline']); ?></small></span>
            </a>
            <nav class="<?php echo esc_attr($desktop_class); ?>" aria-label="Website navigation">
                <?php atlas_performance_local_v5_render_navigation_list($tree, 'atlas-v5-desktop'); ?>
            </nav>
            <?php atlas_performance_local_v5_render_mobile_menu_trigger($payload, $legacy); ?>
        </div>
        <?php atlas_performance_local_v5_render_mobile_drawer($website, $tree, $legacy); ?>
    </header>
    <?php
}

function atlas_performance_local_v5_render_media(array $media, string $class_name, bool $priority = false): void {
    $position = sprintf('%.3f%% %.3f%%', (float) $media['focal_x'] * 100, (float) $media['focal_y'] * 100);
    ?>
    <figure class="performanceLocalMedia <?php echo esc_attr($class_name); ?>">
        <div class="performanceLocalMediaFrame">
            <img
                src="<?php echo esc_url($media['src']); ?>"
                alt="<?php echo esc_attr($media['alt']); ?>"
                <?php if ($media['title'] !== null): ?>title="<?php echo esc_attr($media['title']); ?>"<?php endif; ?>
                decoding="async"
                loading="<?php echo $priority ? 'eager' : 'lazy'; ?>"
                style="object-position:<?php echo esc_attr($position); ?>"
            >
        </div>
    </figure>
    <?php
}

function atlas_performance_local_v5_render_hero_call($website): void {
    if (!is_array($website)
        || !array_key_exists('phone_display', $website)
        || !array_key_exists('phone_href', $website)
        || !atlas_performance_local_v5_text($website['phone_display'], 80)
        || !atlas_performance_local_v5_tel_href($website['phone_href'])) {
        return;
    }
    $phone_display = $website['phone_display'];
    $phone_href = $website['phone_href'];
    ?>
    <a
        class="performanceLocalButton performanceLocalPhone"
        href="<?php echo esc_url($phone_href); ?>"
        aria-label="<?php echo esc_attr('Call ' . $phone_display); ?>"
    >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
            <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6A19.79 19.79 0 0 1 2.12 4.18 2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.69 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.33 1.85.56 2.81.69A2 2 0 0 1 22 16.92z"></path>
        </svg>
        <span><?php echo esc_html('Call ' . $phone_display); ?></span>
    </a>
    <?php
}

function atlas_performance_local_v5_render_hero(array $payload): void {
    $hero = $payload['hero'];
    ?>
    <section class="performanceLocalHero" data-component-key="hero_conversion_section">
        <div class="performanceLocalContainer performanceLocalHeroGrid">
            <div class="performanceLocalHeroContent">
                <p class="performanceLocalEyebrow"><?php echo esc_html($hero['eyebrow']); ?></p>
                <h1><?php echo esc_html($hero['h1']); ?></h1>
                <p class="performanceLocalHeroSummary"><?php echo esc_html($hero['introduction']); ?></p>
                <div class="performanceLocalActionRow performanceLocalHeroActions" data-hero-conversion-actions>
                    <?php atlas_performance_local_v5_render_hero_call($payload['website'] ?? null); ?>
                    <a class="performanceLocalButton performanceLocalButtonSecondary" href="<?php echo esc_url($hero['estimate_action']['href']); ?>"><?php echo esc_html($hero['estimate_action']['label']); ?></a>
                </div>
            </div>
            <?php atlas_performance_local_v5_render_media($hero['media'], 'performanceLocalHeroMedia', true); ?>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_sections(array $sections): void {
    $ordinary_index = 0;
    foreach ($sections as $section) {
        if ($section['key'] === 'final_conversion') { continue; }
        $has_media = $section['media'] !== null;
        $reverse = $has_media && $ordinary_index % 2 === 1;
        $classes = 'performanceLocalSection ' . ($has_media ? 'performanceLocalSplitSection' : 'performanceLocalAuthoritySection');
        if ($reverse) { $classes .= ' performanceLocalSplitReverse'; }
        ?>
        <section class="<?php echo esc_attr($classes); ?>" data-source-section-key="<?php echo esc_attr($section['key']); ?>">
            <div class="performanceLocalContainer performanceLocalSplitGrid">
                <div class="performanceLocalSectionCopy">
                    <h2><?php echo esc_html($section['heading']); ?></h2>
                    <p><?php echo esc_html($section['body']); ?></p>
                </div>
                <?php if ($has_media) { atlas_performance_local_v5_render_media($section['media'], 'performanceLocalSupportingMedia'); } ?>
            </div>
        </section>
        <?php
        $ordinary_index++;
    }
}

function atlas_performance_local_v5_final_conversion(array $sections): ?array {
    $matches = array_values(array_filter(
        $sections,
        fn(array $section): bool => $section['key'] === 'final_conversion'
    ));
    return count($matches) === 1 ? $matches[0] : null;
}

function atlas_performance_local_v5_render_final_conversion(array $payload): void {
    $section = atlas_performance_local_v5_final_conversion($payload['sections']);
    if ($section === null) { return; }
    $website = $payload['website'];
    ?>
    <section class="performanceLocalFinalCta" data-source-section-key="final_conversion">
        <div class="performanceLocalContainer performanceLocalFinalGrid">
            <div class="performanceLocalSectionCopy">
                <h2><?php echo esc_html($section['heading']); ?></h2>
                <p><?php echo esc_html($section['body']); ?></p>
                <div class="performanceLocalActionRow">
                    <a class="performanceLocalButton" href="<?php echo esc_url($website['phone_href']); ?>"><?php echo esc_html($website['phone_display']); ?></a>
                    <a class="performanceLocalButton performanceLocalButtonSecondary" href="<?php echo esc_attr('mailto:' . $website['contact_email']); ?>"><?php echo esc_html($website['contact_email']); ?></a>
                </div>
            </div>
            <?php atlas_performance_local_v5_render_form($payload['form'], true); ?>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_related_pages(array $items): void {
    if (!$items) { return; }
    ?>
    <section class="performanceLocalSection performanceLocalRelated" aria-label="Related destinations">
        <div class="performanceLocalContainer">
            <h2>Related pages</h2>
            <div class="performanceLocalCardGrid">
                <?php foreach ($items as $item): ?>
                    <article data-relationship-type="<?php echo esc_attr($item['relationship_type']); ?>">
                        <h3><a href="<?php echo esc_url($item['href']); ?>"><?php echo esc_html($item['label']); ?></a></h3>
                    </article>
                <?php endforeach; ?>
            </div>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_faq(array $items): void {
    ?>
    <section class="performanceLocalSection performanceLocalFaq" data-component-key="faq_accordion">
        <div class="performanceLocalContainer performanceLocalNarrow">
            <h2>Frequently asked questions</h2>
            <div class="performanceLocalFaqList">
                <?php foreach ($items as $item): ?>
                    <details><summary><?php echo esc_html($item['question']); ?></summary><p><?php echo esc_html($item['answer']); ?></p></details>
                <?php endforeach; ?>
            </div>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_review_trust(?array $module): void {
    if ($module === null) { return; }
    ?>
    <section
        class="performanceLocalV5OptionalModule performanceLocalV5ReviewTrust"
        data-v5-optional-module="review-trust"
        data-v5-optional-presentation="local_rehearsal"
    >
        <div class="performanceLocalV5OptionalContainer">
            <div class="performanceLocalV5OptionalHeading"><p>Independent public sources</p><h2><?php echo esc_html($module['heading']); ?></h2></div>
            <div class="performanceLocalV5ReviewTrustGrid" data-v5-source-count="<?php echo count($module['sources']); ?>">
                <?php foreach ($module['sources'] as $source): ?>
                    <article class="performanceLocalV5ReviewTrustCard" data-v5-source-key="<?php echo esc_attr($source['source_key']); ?>">
                        <div class="performanceLocalV5ReviewTrustBadge performanceLocalV5ReviewTrustBadgeDemo" role="img" aria-label="<?php echo esc_attr($source['badge']['alt']); ?>" data-v5-demo-trust-badge="true"><span>DEMO BADGE — NOT SITE CONTENT</span></div>
                        <div class="performanceLocalV5ReviewTrustCopy">
                            <h3><?php echo esc_html($source['public_name']); ?></h3>
                            <p><?php echo esc_html($source['description']); ?></p>
                            <?php if ($source['rating_text'] !== null || $source['review_count_text'] !== null): ?>
                                <p class="performanceLocalV5ReviewTrustVerification">
                                    <?php if ($source['rating_text'] !== null): ?><span><?php echo esc_html($source['rating_text']); ?></span><?php endif; ?>
                                    <?php if ($source['review_count_text'] !== null): ?><span><?php echo esc_html($source['review_count_text']); ?></span><?php endif; ?>
                                </p>
                            <?php endif; ?>
                        </div>
                    </article>
                <?php endforeach; ?>
            </div>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_location_map(?array $module): void {
    if ($module === null) { return; }
    $city_service_area = $module['mode'] === 'city_service_area';
    ?>
    <section
        class="performanceLocalV5OptionalModule performanceLocalV5LocationMap"
        data-v5-location-mode="<?php echo esc_attr($module['mode']); ?>"
        data-v5-optional-module="location-map"
        data-v5-optional-presentation="local_rehearsal"
        <?php if ($city_service_area): ?>data-v5-service-area-city="<?php echo esc_attr($module['target_city']); ?>" data-v5-service-area-state="<?php echo esc_attr($module['target_state']); ?>"<?php endif; ?>
    >
        <div class="performanceLocalV5OptionalContainer performanceLocalV5LocationMapLayout">
            <div class="performanceLocalV5LocationDetails">
                <h2><?php echo esc_html($module['heading']); ?></h2>
                <?php if (!$city_service_area): ?>
                    <h3><?php echo esc_html($module['approved_location_name']); ?></h3>
                    <address><?php foreach ($module['address_lines'] as $line): ?><span><?php echo esc_html($line); ?></span><?php endforeach; ?></address>
                <?php endif; ?>
                <?php if ($module['description'] !== null): ?><p><?php echo esc_html($module['description']); ?></p><?php endif; ?>
                <?php if (!$city_service_area && ($module['phone_action'] !== null || $module['directions_action'] !== null)): ?>
                    <div class="performanceLocalV5LocationActions">
                        <?php if ($module['phone_action'] !== null): ?><a class="performanceLocalV5OptionalLink" href="<?php echo esc_url($module['phone_action']['href']); ?>"><?php echo esc_html($module['phone_action']['label']); ?></a><?php endif; ?>
                        <?php if ($module['directions_action'] !== null): ?><a class="performanceLocalV5OptionalLink" href="<?php echo esc_url($module['directions_action']['href']); ?>"><?php echo esc_html($module['directions_action']['label']); ?></a><?php endif; ?>
                    </div>
                <?php endif; ?>
            </div>
            <div class="performanceLocalV5MapFrame performanceLocalV5MapFrameDemo" role="img" aria-label="<?php echo esc_attr($module['map_title']); ?>" data-v5-demo-map="true"><span><?php echo esc_html($module['demo_label']); ?></span></div>
        </div>
    </section>
    <?php
}

function atlas_performance_local_v5_render_form(array $form, bool $compact = false): void {
    $classes = 'performanceLocalEstimateForm performanceLocalV5Form';
    if ($compact) { $classes .= ' performanceLocalV5FormCompact'; }
    ?>
    <form
        id="<?php echo esc_attr($form['anchor']); ?>"
        class="<?php echo esc_attr($classes); ?>"
        aria-label="Estimate request preview"
        autocomplete="off"
        data-atlas-v5-inert-form
        data-preview-only="true"
        data-provider-state="disabled"
        data-provider-configured="false"
        data-collects-data="false"
        data-controls-read-only="true"
        data-v5-default-field-count="5"
        data-v5-maximum-field-count="6"
    >
        <p class="performanceLocalV5FormNotice performanceLocalFormNotice" role="note"><?php echo esc_html($form['notice']); ?></p>
        <div class="performanceLocalV5FormGrid">
            <?php foreach ($form['fields'] as $field): ?>
                <label<?php echo $field['control'] === 'textarea' ? ' class="performanceLocalV5FormFieldFull"' : ''; ?>>
                    <span><?php echo esc_html($field['label']); ?></span>
                    <?php if ($field['control'] === 'textarea'): ?>
                        <textarea
                            aria-label="<?php echo esc_attr($field['label']); ?>"
                            data-field-key="<?php echo esc_attr($field['field_key']); ?>"
                            data-field-order="<?php echo esc_attr((string) $field['order']); ?>"
                            maxlength="<?php echo esc_attr((string) $field['maximum_length']); ?>"
                            rows="3"
                            readonly
                            disabled
                            <?php echo $field['required'] ? 'required' : ''; ?>
                        ></textarea>
                    <?php else: ?>
                        <input
                            type="<?php echo esc_attr($field['input_type']); ?>"
                            aria-label="<?php echo esc_attr($field['label']); ?>"
                            data-field-key="<?php echo esc_attr($field['field_key']); ?>"
                            data-field-order="<?php echo esc_attr((string) $field['order']); ?>"
                            maxlength="<?php echo esc_attr((string) $field['maximum_length']); ?>"
                            readonly
                            disabled
                            <?php echo $field['required'] ? 'required' : ''; ?>
                        >
                    <?php endif; ?>
                </label>
            <?php endforeach; ?>
        </div>
        <button type="submit" disabled><?php echo esc_html($form['submit_label']); ?></button>
    </form>
    <?php
}

function atlas_performance_local_v5_render_footer(array $payload, bool $legacy): void {
    $footer = $payload['footer'];
    $footer_class = $legacy ? 'performanceLocalFooter' : 'performanceLocalV5Footer';
    $container = $legacy
        ? 'performanceLocalContainer performanceLocalFooterGrid'
        : 'performanceLocalV5Container performanceLocalV5FooterGrid';
    $brand = $legacy ? 'performanceLocalFooterBrand' : 'performanceLocalV5FooterBrand';
    $contact = $legacy ? 'performanceLocalFooterContact' : 'performanceLocalV5FooterContact';
    ?>
    <footer class="<?php echo esc_attr($footer_class); ?>">
        <div class="<?php echo esc_attr($container); ?>">
            <div class="<?php echo esc_attr($brand); ?>">
                <img class="previewFooterLogo" src="<?php echo esc_url($footer['logo']['src']); ?>" alt="<?php echo esc_attr($footer['logo']['alt']); ?>" loading="lazy" decoding="async">
                <strong><?php echo esc_html($footer['company_name']); ?></strong>
            </div>
            <?php if ($footer['navigation']): ?>
                <nav aria-label="Footer navigation"><ul>
                    <?php foreach ($footer['navigation'] as $item): ?><li><a href="<?php echo esc_url($item['href']); ?>"><?php echo esc_html($item['label']); ?></a></li><?php endforeach; ?>
                </ul></nav>
            <?php endif; ?>
            <div class="<?php echo esc_attr($contact); ?>">
                <a class="<?php echo $legacy ? 'performanceLocalButton' : 'performanceLocalV5Button'; ?>" href="<?php echo esc_url($payload['website']['phone_href']); ?>"><?php echo esc_html($footer['phone_display']); ?></a>
                <span><?php echo esc_html($footer['contact_email']); ?></span>
            </div>
        </div>
    </footer>
    <?php
}

function atlas_performance_local_v5_render_city_service(array $payload): void {
    ?>
    <div class="performanceLocalSite" data-atlas-adapter="performance-local-v5-wordpress" data-atlas-delivery-mode="local-rehearsal" data-mobile-menu-open="false">
        <a class="performanceLocalSkipLink" href="#main-content">Skip to main content</a>
        <?php atlas_performance_local_v5_render_header($payload, true); ?>
        <main id="main-content">
            <?php atlas_performance_local_v5_render_hero($payload); ?>
            <?php atlas_performance_local_v5_render_review_trust($payload['optional_modules']['review_trust']); ?>
            <?php atlas_performance_local_v5_render_sections($payload['sections']); ?>
            <?php atlas_performance_local_v5_render_related_pages($payload['related_pages']); ?>
            <?php atlas_performance_local_v5_render_faq($payload['faq']); ?>
            <?php atlas_performance_local_v5_render_location_map($payload['optional_modules']['location_map']); ?>
            <?php atlas_performance_local_v5_render_final_conversion($payload); ?>
        </main>
        <?php atlas_performance_local_v5_render_footer($payload, true); ?>
    </div>
    <?php
}

function atlas_performance_local_v5_render_estimate(array $payload): void {
    $estimate = $payload['conditional']['estimate'];
    ?>
    <a class="performanceLocalV5SkipLink" href="#performance-local-v5-conditional-main">Skip to main content</a>
    <?php atlas_performance_local_v5_render_header($payload, false); ?>
    <main id="performance-local-v5-conditional-main">
        <section class="performanceLocalV5ConditionalMain performanceLocalV5EstimatePage" data-v5-conditional-layout="estimate">
            <div class="performanceLocalV5Container performanceLocalV5EstimatePageGrid">
                <div class="performanceLocalV5ConditionalLead">
                    <h1><?php echo esc_html($estimate['heading']); ?></h1>
                    <p class="performanceLocalV5ConditionalIntroduction"><?php echo esc_html($estimate['introduction']); ?></p>
                    <?php if ($estimate['phone_alternative_enabled']): ?>
                        <div class="performanceLocalV5ActionRow"><a class="performanceLocalV5Button" href="<?php echo esc_url($payload['website']['phone_href']); ?>"><?php echo esc_html($payload['website']['phone_display']); ?></a></div>
                    <?php endif; ?>
                </div>
                <?php atlas_performance_local_v5_render_form($payload['form']); ?>
            </div>
        </section>
    </main>
    <?php atlas_performance_local_v5_render_footer($payload, false); ?>
    <?php
}

function atlas_performance_local_v5_render_special(array $payload): void {
    $special = $payload['conditional']['special'];
    $action = $payload['sticky_action']['action'];
    ?>
    <a class="performanceLocalV5SkipLink" href="#performance-local-v5-conditional-main">Skip to main content</a>
    <?php atlas_performance_local_v5_render_header($payload, false); ?>
    <main id="performance-local-v5-conditional-main">
        <section class="performanceLocalV5ConditionalMain performanceLocalV5SpecialPage" data-v5-conditional-layout="special" data-v5-demo-special="true">
            <div class="performanceLocalV5Container performanceLocalV5ConditionalContent">
                <div class="performanceLocalV5ConditionalLead">
                    <p class="performanceLocalV5ConditionalEyebrow">Special</p>
                    <h1><?php echo esc_html($special['headline']); ?></h1>
                    <p class="performanceLocalV5ConditionalIntroduction"><?php echo esc_html($special['description']); ?></p>
                    <div class="performanceLocalV5ActionRow">
                        <?php if ($special['call_action_enabled']): ?><a class="performanceLocalV5Button" href="<?php echo esc_url($payload['website']['phone_href']); ?>"><?php echo esc_html($payload['sticky_action']['phone']['label']); ?></a><?php endif; ?>
                        <?php if ($special['estimate_action_enabled'] && $action !== null): ?><a class="performanceLocalV5Button performanceLocalV5ButtonSecondary" href="<?php echo esc_url($action['href']); ?>"><?php echo esc_html($action['label']); ?></a><?php endif; ?>
                    </div>
                </div>
                <?php if ($special['terms'] !== null): ?><aside class="performanceLocalV5SpecialDetails" aria-label="Special details"><section><h2>Terms</h2><p><?php echo esc_html($special['terms']); ?></p></section></aside><?php endif; ?>
            </div>
        </section>
    </main>
    <?php atlas_performance_local_v5_render_footer($payload, false); ?>
    <?php
}

function atlas_performance_local_v5_render_page(array $payload): void {
    if (!atlas_performance_local_v5_payload_is_valid($payload)) { return; }
    $action_enabled = $payload['sticky_action']['action'] !== null;
    $root_classes = 'projectAtlasV5Root ' . ($payload['surface'] === 'city_service'
        ? 'performanceLocalV5CityServicePreview'
        : 'performanceLocalV5Site performanceLocalV5ConditionalPage');
    ?>
    <div
        class="<?php echo esc_attr($root_classes); ?>"
        data-project-atlas-v5-root
        data-v5-site-root="true"
        data-v5-surface="<?php echo esc_attr($payload['surface']); ?>"
        data-v5-top-action-enabled="<?php echo $action_enabled ? 'true' : 'false'; ?>"
        data-v5-menu-open="false"
        data-v5-form-focus-risk="false"
        data-atlas-theme-key="<?php echo esc_attr($payload['theme']['source_theme']['key']); ?>"
        data-atlas-theme-version="<?php echo esc_attr((string) $payload['theme']['source_theme']['version']); ?>"
        data-atlas-theme-token-hash="<?php echo esc_attr($payload['theme']['source_theme']['token_hash_sha256']); ?>"
        data-atlas-runtime-checksum="<?php echo esc_attr(atlas_performance_local_v5_runtime_checksum()); ?>"
        style="<?php echo esc_attr(atlas_performance_local_v5_root_style($payload['theme'])); ?>"
    >
        <?php atlas_performance_local_v5_render_top_stack($payload); ?>
        <?php
        if ($payload['surface'] === 'city_service') { atlas_performance_local_v5_render_city_service($payload); }
        elseif ($payload['surface'] === 'estimate') { atlas_performance_local_v5_render_estimate($payload); }
        else { atlas_performance_local_v5_render_special($payload); }
        ?>
        <button class="performanceLocalV5BackToTop" type="button" data-atlas-v5-back-to-top hidden>Back to top</button>
    </div>
    <?php
}
