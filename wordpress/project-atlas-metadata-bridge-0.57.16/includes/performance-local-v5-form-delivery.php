<?php
/**
 * Contained WordPress-native delivery for the existing Performance Local V5 estimate form.
 */

if (!defined('ABSPATH')) { exit; }

define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION', '_project_atlas_estimate_form_delivery_v1');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_SCHEMA', 'project-atlas-estimate-form-delivery@1');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_TOKEN_SCHEMA', 'project-atlas-performance-local-v5-form-token@1');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY', 'performance-local-v5-estimate');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION', 1);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE_NAMESPACE', 'project-atlas/v4');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE', '/performance-local-v5/estimate');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_MAX_BODY_BYTES', 16384);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDEMPOTENCY_PREFIX', '_project_atlas_v5_form_idem_');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_RATE_PREFIX', 'project_atlas_v5_form_rate_');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_RATE_LOCK_PREFIX', '_project_atlas_v5_form_rate_lock_');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_CLEANUP_HOOK', 'atlas_performance_local_v5_form_cleanup_metadata');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_PENDING_LEASE_SECONDS', 900);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_PAGE', 'project-atlas-v5-form-delivery');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION', 'project_atlas_v5_form_delivery_settings');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION', 'project-atlas-v5-form-delivery-settings@1');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD', 'atlas_v5_form_nonce');
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_TOKEN_TTL_SECONDS', 900);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_IDEMPOTENCY_TTL_SECONDS', 3600);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_WINDOW_SECONDS', 300);
define('ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_MAX_ATTEMPTS', 5);
define(
    'ATLAS_PERFORMANCE_LOCAL_V5_FORM_VALIDATION_MESSAGE',
    'Please check the highlighted fields and try again.'
);

function atlas_performance_local_v5_form_delivery_canonicalize($value) {
    if (is_array($value)) {
        if (!array_is_list($value)) { ksort($value, SORT_STRING); }
        foreach ($value as $key => $item) {
            $value[$key] = atlas_performance_local_v5_form_delivery_canonicalize($item);
        }
    }
    return $value;
}

function atlas_performance_local_v5_form_delivery_canonical_json($value): ?string {
    $json = wp_json_encode(
        atlas_performance_local_v5_form_delivery_canonicalize($value),
        JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE
    );
    return is_string($json) ? $json : null;
}

function atlas_performance_local_v5_form_delivery_exact_record($value, array $keys): bool {
    return function_exists('atlas_performance_local_v5_exact_record')
        && atlas_performance_local_v5_exact_record($value, $keys);
}

function atlas_performance_local_v5_form_delivery_one_line($value, int $maximum): bool {
    return is_string($value)
        && $value !== ''
        && $value === trim($value)
        && strlen($value) <= $maximum
        && wp_check_invalid_utf8($value, true) === $value
        && preg_match('/[\x00-\x1F\x7F<>]/u', $value) !== 1;
}

function atlas_performance_local_v5_form_delivery_email($value): bool {
    return is_string($value)
        && $value !== ''
        && $value === trim($value)
        && preg_match('/[\x00-\x20\x7F]/', $value) !== 1
        && is_email($value) !== false;
}

function atlas_performance_local_v5_form_delivery_email_domain(string $email): ?string {
    $position = strrpos($email, '@');
    if ($position === false || $position === 0 || $position === strlen($email) - 1) { return null; }
    $domain = strtolower(substr($email, $position + 1));
    return preg_match('/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/', $domain) === 1
        ? $domain
        : null;
}

function atlas_performance_local_v5_form_delivery_hash_fields(array $fields): string {
    $json = atlas_performance_local_v5_form_delivery_canonical_json($fields);
    return $json === null ? '' : hash('sha256', $json);
}

function atlas_performance_local_v5_form_delivery_hash_sixth(?array $field): ?string {
    if ($field === null) { return null; }
    $json = atlas_performance_local_v5_form_delivery_canonical_json($field);
    return $json === null ? null : hash('sha256', $json);
}

function atlas_performance_local_v5_form_delivery_governed_email_field(): array {
    return [
        'field_key' => 'email',
        'label' => 'Email',
        'required' => false,
        'control' => 'input',
        'input_type' => 'email',
        'order' => 6,
        'maximum_length' => 254,
        'validation' => [
            'rule' => 'email_address',
            'minimum_length' => 3,
            'maximum_length' => 254,
        ],
    ];
}

function atlas_performance_local_v5_form_delivery_sixth_field_is_safe(array $field): bool {
    $rule = $field['validation']['rule'] ?? null;
    if ($field['control'] === 'textarea') {
        return $field['input_type'] === 'text' && $rule === 'free_text';
    }
    if ($field['control'] !== 'input') { return false; }
    if ($field['input_type'] === 'email') { return $rule === 'email_address'; }
    if ($field['input_type'] === 'tel') { return $rule === 'phone'; }
    return $field['input_type'] === 'text'
        && in_array($rule, ['nonempty_text', 'postal_code', 'free_text'], true);
}

function atlas_performance_local_v5_form_delivery_default_field_contract(array $fields): bool {
    if (!array_is_list($fields) || !in_array(count($fields), [5, 6], true)) { return false; }
    $expected = [
        ['name', 'Name', true, 'input', 'text', 1, 100, 'nonempty_text', 1],
        ['phone', 'Phone', true, 'input', 'tel', 2, 40, 'phone', 6],
        ['postal-code', 'ZIP code', true, 'input', 'text', 3, 12, 'postal_code', 5],
        ['requested-service', 'Requested service', true, 'input', 'text', 4, 160, 'nonempty_text', 1],
        ['message', 'Optional message', false, 'textarea', 'text', 5, 2000, 'free_text', 0],
    ];
    foreach ($expected as $index => $values) {
        $field = $fields[$index] ?? null;
        if (!atlas_performance_local_v5_form_delivery_exact_record($field, [
            'field_key', 'label', 'required', 'control', 'input_type', 'order',
            'maximum_length', 'validation',
        ]) || !atlas_performance_local_v5_form_delivery_exact_record(
            $field['validation'],
            ['rule', 'minimum_length', 'maximum_length']
        )) { return false; }
        $actual = [
            $field['field_key'], $field['label'], $field['required'], $field['control'],
            $field['input_type'], $field['order'], $field['maximum_length'],
            $field['validation']['rule'], $field['validation']['minimum_length'],
        ];
        if ($actual !== $values || $field['validation']['maximum_length'] !== $values[6]) { return false; }
    }
    return count($fields) === 5
        || function_exists('atlas_performance_local_v5_form_field')
            && atlas_performance_local_v5_form_field($fields[5], 5)
            && atlas_performance_local_v5_form_delivery_sixth_field_is_safe($fields[5]);
}

function atlas_performance_local_v5_form_delivery_allowed_subject($template): bool {
    if (!is_string($template) || !atlas_performance_local_v5_form_delivery_one_line($template, 200)) { return false; }
    $without = str_replace(
        ['{{company_name}}', '{{page_title}}', '{{site_name}}'],
        '',
        $template
    );
    return !str_contains($without, '{{') && !str_contains($without, '}}');
}

function atlas_performance_local_v5_form_delivery_configuration_errors($value, ?array $payload = null): array {
    $errors = [];
    $keys = [
        'schema_version', 'enabled', 'website_identity', 'form_identity', 'form_version',
        'field_definition_hash', 'recipient_email', 'from_name', 'from_email',
        'subject_template', 'success_message', 'failure_message', 'token_ttl_seconds',
        'idempotency_ttl_seconds', 'rate_window_seconds', 'rate_max_attempts',
        'reply_to', 'optional_sixth_field',
    ];
    if (!atlas_performance_local_v5_form_delivery_exact_record($value, $keys)) {
        return ['Configuration keys differ from the exact delivery contract.'];
    }
    if ($value['schema_version'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_SCHEMA) { $errors[] = 'Configuration schema differs.'; }
    if (!is_bool($value['enabled'])) { $errors[] = 'Enabled state is invalid.'; }
    if (!atlas_performance_local_v5_form_delivery_one_line($value['website_identity'], 240)) { $errors[] = 'Website identity is invalid.'; }
    if ($value['form_identity'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY) { $errors[] = 'Form identity differs.'; }
    if ($value['form_version'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION) { $errors[] = 'Form version differs.'; }
    if (!is_string($value['field_definition_hash']) || preg_match('/^[a-f0-9]{64}$/', $value['field_definition_hash']) !== 1) { $errors[] = 'Field hash is invalid.'; }
    if (!atlas_performance_local_v5_form_delivery_email($value['recipient_email'])) { $errors[] = 'Recipient is invalid.'; }
    if (!atlas_performance_local_v5_form_delivery_one_line($value['from_name'], 120)) { $errors[] = 'From name is invalid.'; }
    if (!atlas_performance_local_v5_form_delivery_email($value['from_email'])) { $errors[] = 'From email is invalid.'; }
    if (!atlas_performance_local_v5_form_delivery_allowed_subject($value['subject_template'])) { $errors[] = 'Subject template is invalid.'; }
    foreach (['success_message', 'failure_message'] as $message_key) {
        if (!atlas_performance_local_v5_form_delivery_one_line($value[$message_key], 500)) {
            $errors[] = 'Public message is invalid.';
        }
    }
    foreach ([
        'token_ttl_seconds' => [300, 86400],
        'idempotency_ttl_seconds' => [60, 86400],
        'rate_window_seconds' => [60, 3600],
        'rate_max_attempts' => [1, 20],
    ] as $key => [$minimum, $maximum]) {
        if (!is_int($value[$key]) || $value[$key] < $minimum || $value[$key] > $maximum) {
            $errors[] = 'A duration or rate bound is invalid.';
        }
    }
    $reply_to_valid = atlas_performance_local_v5_form_delivery_exact_record(
        $value['reply_to'],
        ['enabled', 'field_key']
    )
        && is_bool($value['reply_to']['enabled'])
        && ($value['reply_to']['field_key'] === null
            || is_string($value['reply_to']['field_key'])
                && preg_match('/^[a-z][a-z0-9_-]{0,119}$/', $value['reply_to']['field_key']) === 1);
    if (!$reply_to_valid) {
        $errors[] = 'Reply-To configuration is invalid.';
    }
    $reply_to = $reply_to_valid
        ? $value['reply_to']
        : ['enabled' => false, 'field_key' => null];
    $sixth_binding = $value['optional_sixth_field'];
    if ($sixth_binding !== null
        && (!atlas_performance_local_v5_form_delivery_exact_record(
            $sixth_binding,
            ['field_key', 'input_type', 'definition_hash']
        )
            || !is_string($sixth_binding['field_key'])
            || preg_match('/^[a-z][a-z0-9_-]{0,119}$/', $sixth_binding['field_key']) !== 1
            || !in_array($sixth_binding['input_type'], ['text', 'tel', 'email'], true)
            || !is_string($sixth_binding['definition_hash'])
            || preg_match('/^[a-f0-9]{64}$/', $sixth_binding['definition_hash']) !== 1)) {
        $errors[] = 'Optional sixth-field binding is invalid.';
    }
    if ($reply_to_valid) {
        if (!$reply_to['enabled'] && $reply_to['field_key'] !== null) {
            $errors[] = 'Disabled Reply-To must not bind a field.';
        }
        if ($reply_to['enabled'] && ($sixth_binding === null
            || $reply_to['field_key'] !== ($sixth_binding['field_key'] ?? null)
            || ($sixth_binding['input_type'] ?? null) !== 'email')) {
            $errors[] = 'Enabled Reply-To requires the exact optional email field.';
        }
    }

    if ($payload !== null) {
        if (!function_exists('atlas_performance_local_v5_payload_is_valid')
            || !atlas_performance_local_v5_payload_is_valid($payload)
            || !in_array($payload['surface'] ?? null, ['city_service', 'estimate'], true)
            || !isset($payload['form']['fields'])
            || !is_array($payload['form']['fields'])
            || !atlas_performance_local_v5_form_delivery_default_field_contract($payload['form']['fields'])) {
            $errors[] = 'Rendered V5 form contract is invalid.';
        } else {
            $fields = $payload['form']['fields'];
            $sixth = count($fields) === 6 ? $fields[5] : null;
            $expected_binding = $sixth === null ? null : [
                'field_key' => $sixth['field_key'],
                'input_type' => $sixth['input_type'],
                'definition_hash' => atlas_performance_local_v5_form_delivery_hash_sixth($sixth),
            ];
            if ($value['website_identity'] !== $payload['website']['identity']) { $errors[] = 'Website identity does not match the rendered page.'; }
            if ($value['field_definition_hash'] !== atlas_performance_local_v5_form_delivery_hash_fields($fields)) { $errors[] = 'Field definition does not match the rendered form.'; }
            if (atlas_performance_local_v5_form_delivery_canonicalize($sixth_binding)
                !== atlas_performance_local_v5_form_delivery_canonicalize($expected_binding)) {
                $errors[] = 'Optional sixth-field binding does not match the rendered form.';
            }
            if ($sixth === null && ($reply_to['enabled'] || $reply_to['field_key'] !== null)) {
                $errors[] = 'Five-field forms cannot enable Reply-To.';
            }
            if ($sixth !== null && $reply_to['enabled']
                && ($sixth['input_type'] !== 'email'
                    || $sixth['validation']['rule'] !== 'email_address'
                    || $reply_to['field_key'] !== $sixth['field_key'])) {
                $errors[] = 'Reply-To does not match the governed sixth email field.';
            }
            if (!atlas_performance_local_v5_form_delivery_from_domain_is_allowed($value['from_email'])) {
                $errors[] = 'From email does not use the governed Website domain.';
            }
            if (atlas_performance_local_v5_form_delivery_allowed_subject($value['subject_template'])
                && atlas_performance_local_v5_form_delivery_subject($value, $payload) === null) {
                $errors[] = 'Expanded subject is invalid.';
            }
        }
    }
    if (is_string($value['recipient_email'] ?? null) && is_string($value['from_email'] ?? null)) {
        foreach (['success_message', 'failure_message'] as $message_key) {
            $message = is_string($value[$message_key]) ? strtolower($value[$message_key]) : '';
            if (str_contains($message, strtolower($value['recipient_email']))
                || str_contains($message, strtolower($value['from_email']))) {
                $errors[] = 'Public messages must not expose delivery addresses.';
            }
        }
    }
    return array_values(array_unique($errors));
}

function atlas_performance_local_v5_form_delivery_governed_field_contract_matches(
    array $config,
    array $payload
): bool {
    $fields = $payload['form']['fields'] ?? null;
    if (!is_array($fields) || !array_is_list($fields)) { return false; }
    if (count($fields) === 5) {
        return ($config['optional_sixth_field'] ?? null) === null
            && ($config['reply_to'] ?? null) === [
                'enabled' => false,
                'field_key' => null,
            ];
    }
    if (count($fields) !== 6
        || $fields[5] !== atlas_performance_local_v5_form_delivery_governed_email_field()) {
        return false;
    }
    $expected_binding = [
        'field_key' => 'email',
        'input_type' => 'email',
        'definition_hash' => atlas_performance_local_v5_form_delivery_hash_sixth($fields[5]),
    ];
    return ($config['optional_sixth_field'] ?? null) === $expected_binding
        && in_array(($config['reply_to'] ?? null), [
            ['enabled' => false, 'field_key' => null],
            ['enabled' => true, 'field_key' => 'email'],
        ], true);
}

function atlas_performance_local_v5_form_delivery_config_for_payload(array $payload): ?array {
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    if (!is_array($config) || ($config['enabled'] ?? null) !== true
        || !atlas_performance_local_v5_form_delivery_governed_field_contract_matches(
            $config,
            $payload
        )
        || atlas_performance_local_v5_form_delivery_configuration_errors($config, $payload) !== []) {
        return null;
    }
    return $config;
}

function atlas_performance_local_v5_form_delivery_admin_target_payload(): ?array {
    if (!defined('ATLAS_METADATA_POST_ID') || !defined('ATLAS_PERFORMANCE_LOCAL_V5_META_KEY')) {
        return null;
    }
    $post = get_post(ATLAS_METADATA_POST_ID);
    $payload = get_post_meta(
        ATLAS_METADATA_POST_ID,
        ATLAS_PERFORMANCE_LOCAL_V5_META_KEY,
        true
    );
    if (!($post instanceof WP_Post) || $post->post_type !== 'page'
        || $post->post_status !== 'publish' || !is_array($payload)
        || !function_exists('atlas_performance_local_v5_payload_is_valid')
        || !atlas_performance_local_v5_payload_is_valid($payload)
        || !in_array($payload['surface'] ?? null, ['city_service', 'estimate'], true)
        || ($payload['payload_identity']['source_page'] ?? null) !== 'generated-page:41'
        || ($payload['payload_identity']['source_composition'] ?? null)
            !== 'composition:41:v10'
        || ($payload['payload_identity']['source_hash'] ?? null)
            !== '19f313d10c024cbc988c7cac63e15bb5e7ea78b14c65af243f41e23f5967af32'
        || ($payload['website']['identity'] ?? null) !== 'website:1') {
        return null;
    }
    return $payload;
}

function atlas_performance_local_v5_form_delivery_admin_target_fields(
    array $payload,
    bool $optional_email_enabled
): ?array {
    $fields = $payload['form']['fields'] ?? null;
    if (!is_array($fields) || !array_is_list($fields)
        || !in_array(count($fields), [5, 6], true)) { return null; }
    $governed_email = atlas_performance_local_v5_form_delivery_governed_email_field();
    if ($optional_email_enabled) {
        if (count($fields) === 5) {
            $fields[] = $governed_email;
        } elseif ($fields[5] !== $governed_email) {
            return null;
        }
    } else {
        $fields = array_slice($fields, 0, 5);
    }
    return atlas_performance_local_v5_form_delivery_default_field_contract($fields)
        ? $fields
        : null;
}

function atlas_performance_local_v5_form_delivery_admin_scalar(array $input, string $key): ?string {
    if (!array_key_exists($key, $input) || !is_string($input[$key])) { return null; }
    $value = wp_unslash($input[$key]);
    return is_string($value) ? $value : null;
}

function atlas_performance_local_v5_form_delivery_admin_allowed_keys($command): ?array {
    $base = [
        'action',
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,
        'atlas_command',
    ];
    if ($command === 'replace_configuration') {
        return array_merge($base, [
            'recipient_email', 'from_name', 'from_email', 'subject_template',
            'success_message', 'failure_message', 'optional_sixth_field_mode',
            'reply_to_mode',
        ]);
    }
    if ($command === 'add_governed_customer_email') {
        return array_merge($base, ['expected_prior_sha256']);
    }
    return in_array(
        $command,
        ['enable_delivery', 'disable_delivery', 'remove_disabled_configuration'],
        true
    )
        ? $base
        : null;
}

function atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input): bool {
    if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST'
        || !atlas_performance_local_v5_environment_is_allowed()
        || !is_admin() || !current_user_can('manage_options')
        || !is_array($input) || array_is_list($input)) {
        return false;
    }
    $nonce = atlas_performance_local_v5_form_delivery_admin_scalar(
        $input,
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD
    );
    if ($nonce === null || wp_verify_nonce(
        $nonce,
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION
    ) === false) {
        return false;
    }
    $command = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'atlas_command');
    $allowed_keys = atlas_performance_local_v5_form_delivery_admin_allowed_keys($command);
    $authorized = $allowed_keys !== null
        && atlas_performance_local_v5_form_delivery_exact_record($input, $allowed_keys)
        && atlas_performance_local_v5_form_delivery_admin_scalar($input, 'action')
            === ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION;
    if (!$authorized || $command !== 'add_governed_customer_email') { return $authorized; }
    $expected = atlas_performance_local_v5_form_delivery_admin_scalar(
        $input,
        'expected_prior_sha256'
    );
    return is_string($expected) && preg_match('/^[a-f0-9]{64}$/D', $expected) === 1;
}

function atlas_performance_local_v5_form_delivery_admin_replacement_email(
    array $input,
    string $key,
    $existing
): ?string {
    $submitted = atlas_performance_local_v5_form_delivery_admin_scalar($input, $key);
    if ($submitted === null) { return null; }
    if ($submitted !== '') {
        return atlas_performance_local_v5_form_delivery_email($submitted) ? $submitted : null;
    }
    $saved = is_array($existing) ? ($existing[$key] ?? null) : null;
    return atlas_performance_local_v5_form_delivery_email($saved) ? $saved : null;
}

function atlas_performance_local_v5_form_delivery_admin_candidate(array $input): ?array {
    $payload = atlas_performance_local_v5_form_delivery_admin_target_payload();
    if ($payload === null) { return null; }
    $optional_mode = atlas_performance_local_v5_form_delivery_admin_scalar(
        $input,
        'optional_sixth_field_mode'
    );
    $reply_to_mode = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'reply_to_mode');
    if (!in_array($optional_mode, ['enabled', 'disabled'], true)
        || !in_array($reply_to_mode, ['enabled', 'disabled'], true)
        || ($reply_to_mode === 'enabled' && $optional_mode !== 'enabled')) {
        return null;
    }
    $target_fields = atlas_performance_local_v5_form_delivery_admin_target_fields(
        $payload,
        $optional_mode === 'enabled'
    );
    if ($target_fields === null) { return null; }
    $existing = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    $recipient = atlas_performance_local_v5_form_delivery_admin_replacement_email(
        $input,
        'recipient_email',
        $existing
    );
    $from = atlas_performance_local_v5_form_delivery_admin_replacement_email(
        $input,
        'from_email',
        $existing
    );
    $from_name = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'from_name');
    $subject = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'subject_template');
    $success = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'success_message');
    $failure = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'failure_message');
    if ($recipient === null || $from === null || $from_name === null || $subject === null
        || $success === null || $failure === null
        || !atlas_performance_local_v5_form_delivery_from_domain_is_allowed($from)) {
        return null;
    }
    $governed_email = atlas_performance_local_v5_form_delivery_governed_email_field();
    $optional_binding = $optional_mode === 'enabled'
        ? [
            'field_key' => $governed_email['field_key'],
            'input_type' => $governed_email['input_type'],
            'definition_hash' => atlas_performance_local_v5_form_delivery_hash_sixth(
                $governed_email
            ),
        ]
        : null;
    $candidate = [
        'schema_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_SCHEMA,
        'enabled' => false,
        'website_identity' => $payload['website']['identity'],
        'form_identity' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY,
        'form_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION,
        'field_definition_hash' => atlas_performance_local_v5_form_delivery_hash_fields(
            $target_fields
        ),
        'recipient_email' => $recipient,
        'from_name' => $from_name,
        'from_email' => $from,
        'subject_template' => $subject,
        'success_message' => $success,
        'failure_message' => $failure,
        'token_ttl_seconds' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_TOKEN_TTL_SECONDS,
        'idempotency_ttl_seconds' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_IDEMPOTENCY_TTL_SECONDS,
        'rate_window_seconds' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_WINDOW_SECONDS,
        'rate_max_attempts' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_DEFAULT_RATE_MAX_ATTEMPTS,
        'reply_to' => [
            'enabled' => $reply_to_mode === 'enabled',
            'field_key' => $reply_to_mode === 'enabled' ? $governed_email['field_key'] : null,
        ],
        'optional_sixth_field' => $optional_binding,
    ];
    return atlas_performance_local_v5_form_delivery_configuration_errors($candidate) === []
        ? $candidate
        : null;
}

function atlas_performance_local_v5_form_delivery_admin_optional_mode($binding): string {
    if ($binding === null) { return 'disabled'; }
    $field = atlas_performance_local_v5_form_delivery_governed_email_field();
    $expected = [
        'field_key' => $field['field_key'],
        'input_type' => $field['input_type'],
        'definition_hash' => atlas_performance_local_v5_form_delivery_hash_sixth($field),
    ];
    return $binding === $expected ? 'enabled' : 'invalid';
}

function atlas_performance_local_v5_form_delivery_admin_reply_to_mode($reply_to): string {
    if (!atlas_performance_local_v5_form_delivery_exact_record($reply_to, ['enabled', 'field_key'])
        || !is_bool($reply_to['enabled'])) { return 'invalid'; }
    if ($reply_to === ['enabled' => false, 'field_key' => null]) { return 'disabled'; }
    return $reply_to === ['enabled' => true, 'field_key' => 'email'] ? 'enabled' : 'invalid';
}

function atlas_performance_local_v5_form_delivery_admin_field_definition_matches(
    array $config,
    array $payload
): bool {
    $optional_mode = atlas_performance_local_v5_form_delivery_admin_optional_mode(
        $config['optional_sixth_field'] ?? null
    );
    if ($optional_mode === 'invalid') { return false; }
    $target_fields = atlas_performance_local_v5_form_delivery_admin_target_fields(
        $payload,
        $optional_mode === 'enabled'
    );
    return $target_fields !== null
        && ($payload['form']['fields'] ?? null) === $target_fields
        && hash_equals(
            atlas_performance_local_v5_form_delivery_hash_fields($target_fields),
            (string) ($config['field_definition_hash'] ?? '')
        );
}

function atlas_performance_local_v5_form_delivery_admin_redacted_status(): array {
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    $configured = is_array($config);
    $payload = atlas_performance_local_v5_form_delivery_admin_target_payload();
    return [
        'configured' => $configured,
        'enabled' => $configured && ($config['enabled'] ?? null) === true,
        'schema_valid' => $configured
            && atlas_performance_local_v5_form_delivery_configuration_errors($config) === [],
        'field_definition_hash_match' => $configured && is_array($payload)
            && atlas_performance_local_v5_form_delivery_admin_field_definition_matches(
                $config,
                $payload
            ),
        'recipient_present' => $configured
            && is_string($config['recipient_email'] ?? null)
            && ($config['recipient_email'] ?? '') !== '',
        'from_present' => $configured
            && is_string($config['from_email'] ?? null)
            && ($config['from_email'] ?? '') !== '',
        'from_domain_valid' => $configured
            && atlas_performance_local_v5_form_delivery_from_domain_is_allowed(
                $config['from_email'] ?? null
            ),
        'reply_to_mode' => $configured
            ? atlas_performance_local_v5_form_delivery_admin_reply_to_mode(
                $config['reply_to'] ?? null
            )
            : 'unconfigured',
        'optional_sixth_field_mode' => $configured
            ? atlas_performance_local_v5_form_delivery_admin_optional_mode(
                $config['optional_sixth_field'] ?? null
            )
            : 'unconfigured',
    ];
}

function atlas_performance_local_v5_form_delivery_admin_write_verified(array $candidate): string {
    $sentinel = new stdClass();
    $prior = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $sentinel);
    $prior_exists = $prior !== $sentinel;
    update_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $candidate, false);
    $readback = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $sentinel);
    if ($readback === $candidate) { return 'saved'; }

    if ($prior_exists) {
        update_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $prior, false);
    } else {
        delete_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION);
    }
    $rollback_sentinel = new stdClass();
    $restored = get_option(
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION,
        $rollback_sentinel
    );
    return ($prior_exists && $restored === $prior)
        || (!$prior_exists && $restored === $rollback_sentinel)
            ? 'write_failed_prior_restored'
            : 'write_failed_rollback_failed';
}

function atlas_performance_local_v5_form_delivery_admin_enable_candidate(): ?array {
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    $payload = atlas_performance_local_v5_form_delivery_admin_target_payload();
    if (!is_array($config) || $payload === null
        || !atlas_performance_local_v5_form_delivery_admin_field_definition_matches(
            $config,
            $payload
        )) { return null; }
    $candidate = $config;
    $candidate['enabled'] = true;
    return atlas_performance_local_v5_form_delivery_configuration_errors(
        $candidate,
        $payload
    ) === [] ? $candidate : null;
}

function atlas_performance_local_v5_form_delivery_admin_disable_candidate(): ?array {
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    if (!is_array($config)) { return null; }
    $candidate = $config;
    $candidate['enabled'] = false;
    return atlas_performance_local_v5_form_delivery_configuration_errors($candidate) === []
        ? $candidate
        : null;
}

function atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified(): string {
    $sentinel = new stdClass();
    $prior = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $sentinel);
    if (!is_array($prior) || ($prior['enabled'] ?? null) !== false
        || atlas_performance_local_v5_form_delivery_configuration_errors($prior) !== []) {
        return 'rejected';
    }
    delete_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION);
    $readback = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $sentinel);
    if ($readback === $sentinel) { return 'removed'; }
    if ($readback !== $prior) {
        update_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $prior, false);
    }
    $restored = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, $sentinel);
    return $restored === $prior
        ? 'remove_failed_prior_restored'
        : 'remove_failed_rollback_failed';
}

function atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_candidate(
    array $payload
): ?array {
    $fields = $payload['form']['fields'] ?? null;
    if (!is_array($fields) || !array_is_list($fields)) {
        return null;
    }
    $candidate = $payload;
    $governed_email = atlas_performance_local_v5_form_delivery_governed_email_field();
    if (count($fields) === 5
        && atlas_performance_local_v5_form_delivery_default_field_contract($fields)) {
        $candidate['form']['fields'][] = $governed_email;
    } elseif (count($fields) !== 6
        || !atlas_performance_local_v5_form_delivery_default_field_contract(
            array_slice($fields, 0, 5)
        )
        || ($fields[5] ?? null) !== $governed_email) {
        return null;
    }
    return function_exists('atlas_performance_local_v5_payload_is_valid')
        && atlas_performance_local_v5_payload_is_valid($candidate)
            ? $candidate
            : null;
}

function atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_configuration_is_ready(
    $config,
    array $candidate
): bool {
    return is_array($config)
        && ($config['enabled'] ?? null) === false
        && ($config['reply_to'] ?? null) === [
            'enabled' => true,
            'field_key' => 'email',
        ]
        && atlas_performance_local_v5_form_delivery_governed_field_contract_matches(
            $config,
            $candidate
        )
        && atlas_performance_local_v5_form_delivery_configuration_errors(
            $config,
            $candidate
        ) === [];
}

function atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state(): array {
    $payload = atlas_performance_local_v5_form_delivery_admin_target_payload();
    $current_hash = is_array($payload)
        && function_exists('atlas_performance_local_v5_page_payload_sha256')
            ? atlas_performance_local_v5_page_payload_sha256($payload)
            : null;
    $candidate = is_array($payload)
        ? atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_candidate($payload)
        : null;
    $target_hash = is_array($candidate)
        ? atlas_performance_local_v5_page_payload_sha256($candidate)
        : null;
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    $configuration_ready = is_array($candidate)
        && atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_configuration_is_ready(
            $config,
            $candidate
        );
    $fields = is_array($payload) ? ($payload['form']['fields'] ?? null) : null;
    $governed_email_present = is_array($fields) && array_is_list($fields)
        && count($fields) === 6
        && ($fields[5] ?? null)
            === atlas_performance_local_v5_form_delivery_governed_email_field();
    return [
        'metadata_valid' => is_array($payload) && is_string($current_hash),
        'metadata_sha256' => is_string($current_hash) ? $current_hash : null,
        'source_exact' => is_array($payload),
        'field_count' => is_array($fields) && array_is_list($fields) ? count($fields) : null,
        'governed_email_present' => $governed_email_present,
        'configuration_ready_disabled' => $configuration_ready,
        'upgrade_available' => $configuration_ready
            && is_string($current_hash)
            && is_string($target_hash),
        'target_sha256' => is_string($target_hash) ? $target_hash : null,
    ];
}

function atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
    array $input
): string {
    $expected = atlas_performance_local_v5_form_delivery_admin_scalar(
        $input,
        'expected_prior_sha256'
    );
    if (!is_string($expected) || preg_match('/^[a-f0-9]{64}$/D', $expected) !== 1
        || !function_exists('atlas_performance_local_v5_page_payload_sha256')
        || !function_exists('atlas_performance_local_v5_page_payload_permission')
        || !function_exists('atlas_performance_local_v5_page_payload_apply')
        || !class_exists('WP_REST_Request')) {
        return 'metadata_email_rejected';
    }
    $payload = atlas_performance_local_v5_form_delivery_admin_target_payload();
    $candidate = is_array($payload)
        ? atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_candidate($payload)
        : null;
    $current_hash = is_array($payload)
        ? atlas_performance_local_v5_page_payload_sha256($payload)
        : null;
    if (!is_array($candidate) || !is_string($current_hash)
        || !hash_equals($expected, $current_hash)) {
        return 'metadata_email_rejected';
    }
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    if (!atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_configuration_is_ready(
        $config,
        $candidate
    )) {
        return 'metadata_email_rejected';
    }
    $resulting_hash = atlas_performance_local_v5_page_payload_sha256($candidate);
    $request_identity = wp_generate_uuid4();
    if (!is_string($resulting_hash)
        || preg_match('/^[a-f0-9]{64}$/D', $resulting_hash) !== 1
        || !is_string($request_identity)
        || preg_match(
            '/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/D',
            $request_identity
        ) !== 1) {
        return 'metadata_email_rejected';
    }
    $envelope = [
        'request_schema' => ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_REQUEST_SCHEMA,
        'expected_prior_sha256' => $expected,
        'website_id' => 1,
        'planned_page_id' => 41,
        'generated_page_id' => 41,
        'wordpress_post_id' => ATLAS_METADATA_POST_ID,
        'payload' => $candidate,
        'request_identity' => $request_identity,
    ];
    $encoded = wp_json_encode(
        $envelope,
        JSON_UNESCAPED_SLASHES
            | JSON_UNESCAPED_UNICODE
            | JSON_UNESCAPED_LINE_TERMINATORS
            | JSON_PRESERVE_ZERO_FRACTION
    );
    if (!is_string($encoded)) { return 'metadata_email_rejected'; }
    $request = new WP_REST_Request(
        'POST',
        '/project-atlas/v4/performance-local-v5/page-payload/'
            . (string) ATLAS_METADATA_POST_ID
    );
    $request->set_url_params(['post_id' => (string) ATLAS_METADATA_POST_ID]);
    $request->set_header('content-type', 'application/json');
    $request->set_body($encoded);
    $permission = atlas_performance_local_v5_page_payload_permission($request);
    if ($permission !== true) { return 'metadata_email_rejected'; }
    $result = atlas_performance_local_v5_page_payload_apply($request);
    if (is_wp_error($result)) { return 'metadata_email_rejected'; }
    $response = rest_ensure_response($result);
    $data = $response instanceof WP_REST_Response ? $response->get_data() : null;
    if (!($response instanceof WP_REST_Response) || $response->get_status() !== 200
        || !atlas_performance_local_v5_form_delivery_exact_record($data, [
            'route_schema', 'metadata_bridge_version', 'status', 'post_id',
            'prior_sha256', 'resulting_sha256', 'website_id', 'planned_page_id',
            'generated_page_id', 'request_identity', 'metadata_valid',
        ])
        || ($data['route_schema'] ?? null)
            !== ATLAS_PERFORMANCE_LOCAL_V5_PAGE_PAYLOAD_ROUTE_SCHEMA
        || ($data['metadata_bridge_version'] ?? null) !== ATLAS_METADATA_BRIDGE_VERSION
        || !in_array($data['status'] ?? null, ['APPLIED', 'UNCHANGED'], true)
        || ($data['post_id'] ?? null) !== ATLAS_METADATA_POST_ID
        || ($data['prior_sha256'] ?? null) !== $expected
        || ($data['resulting_sha256'] ?? null) !== $resulting_hash
        || ($data['website_id'] ?? null) !== 1
        || ($data['planned_page_id'] ?? null) !== 41
        || ($data['generated_page_id'] ?? null) !== 41
        || ($data['request_identity'] ?? null) !== $request_identity
        || ($data['metadata_valid'] ?? null) !== true) {
        return 'metadata_email_verification_failed';
    }
    $readback = atlas_performance_local_v5_form_delivery_admin_target_payload();
    $readback_hash = is_array($readback)
        ? atlas_performance_local_v5_page_payload_sha256($readback)
        : null;
    $config_readback = get_option(
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION,
        null
    );
    if ($readback !== $candidate || $readback_hash !== $resulting_hash
        || $config_readback !== $config
        || ($config_readback['enabled'] ?? null) !== false) {
        return 'metadata_email_verification_failed';
    }
    return ($data['status'] ?? null) === 'APPLIED'
        ? 'metadata_email_applied'
        : 'metadata_email_unchanged';
}

function atlas_performance_local_v5_form_delivery_admin_register_page(): void {
    if (!atlas_performance_local_v5_environment_is_allowed()) { return; }
    add_options_page(
        'Performance Local V5 Form Delivery',
        'V5 Form Delivery',
        'manage_options',
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_PAGE,
        'atlas_performance_local_v5_form_delivery_admin_render_page'
    );
}
add_action('admin_menu', 'atlas_performance_local_v5_form_delivery_admin_register_page');

function atlas_performance_local_v5_form_delivery_admin_status_text($value): string {
    if (is_bool($value)) { return $value ? 'Yes' : 'No'; }
    return is_string($value) && in_array(
        $value,
        ['enabled', 'disabled', 'invalid', 'unconfigured'],
        true
    ) ? ucfirst($value) : 'Invalid';
}

function atlas_performance_local_v5_form_delivery_admin_render_page(): void {
    if (!atlas_performance_local_v5_environment_is_allowed()
        || !is_admin() || !current_user_can('manage_options')) {
        wp_die('This settings page is unavailable.', 'Request rejected.', ['response' => 403]);
    }
    $status = atlas_performance_local_v5_form_delivery_admin_redacted_status();
    $metadata = atlas_performance_local_v5_form_delivery_admin_metadata_upgrade_state();
    $notice_key = isset($_GET['atlas_v5_form_status'])
        && is_string($_GET['atlas_v5_form_status'])
        ? wp_unslash($_GET['atlas_v5_form_status'])
        : '';
    $notices = [
        'saved' => 'The private configuration was saved with delivery disabled.',
        'enabled' => 'Delivery was enabled after exact payload verification.',
        'disabled' => 'Delivery was disabled without deleting the configuration.',
        'removed' => 'The disabled configuration was removed after exact absence verification.',
        'rejected' => 'The settings request was rejected without changing the option.',
        'write_failed_prior_restored' => 'The write could not be verified; the prior option was restored.',
        'write_failed_rollback_failed' => 'The write and automatic rollback could not be verified.',
        'remove_failed_prior_restored' => 'Removal could not be verified; the disabled configuration remains intact.',
        'remove_failed_rollback_failed' => 'Removal and automatic restoration could not be verified.',
        'metadata_email_applied' => 'The governed Email field was added to Page 8 metadata and verified.',
        'metadata_email_unchanged' => 'Page 8 metadata already matched the governed six-field target.',
        'metadata_email_rejected' => 'The Page 8 metadata request was rejected without changing metadata.',
        'metadata_email_verification_failed' => 'Page 8 metadata verification failed; review the route result before continuing.',
    ];
    $action_url = admin_url('admin-post.php');
    ?>
    <div class="wrap" data-atlas-v5-form-delivery-settings>
        <h1>Performance Local V5 Form Delivery</h1>
        <?php if (isset($notices[$notice_key])): ?>
            <div class="notice notice-info"><p><?php echo esc_html($notices[$notice_key]); ?></p></div>
        <?php endif; ?>
        <h2>Redacted status</h2>
        <table class="widefat striped" data-atlas-v5-form-delivery-status>
            <tbody>
                <?php foreach ($status as $key => $value): ?>
                    <tr data-atlas-v5-status="<?php echo esc_attr($key); ?>">
                        <th scope="row"><?php echo esc_html(str_replace('_', ' ', ucfirst($key))); ?></th>
                        <td><?php echo esc_html(atlas_performance_local_v5_form_delivery_admin_status_text($value)); ?></td>
                    </tr>
                <?php endforeach; ?>
            </tbody>
        </table>

        <h2>Replace configuration</h2>
        <p>Replacement fields are blank. A replacement is always saved with delivery disabled.</p>
        <form method="post" action="<?php echo esc_url($action_url); ?>" autocomplete="off">
            <input type="hidden" name="action" value="<?php echo esc_attr(ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION); ?>">
            <input type="hidden" name="atlas_command" value="replace_configuration">
            <?php wp_nonce_field(
                ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION,
                ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,
                false,
                true
            ); ?>
            <table class="form-table" role="presentation"><tbody>
                <tr><th scope="row"><label for="atlas-v5-recipient">Recipient email</label></th><td><input id="atlas-v5-recipient" name="recipient_email" type="email" value="" autocomplete="off"></td></tr>
                <tr><th scope="row"><label for="atlas-v5-from-name">From name</label></th><td><input id="atlas-v5-from-name" name="from_name" type="text" value="" maxlength="120" autocomplete="off" required></td></tr>
                <tr><th scope="row"><label for="atlas-v5-from-email">From email</label></th><td><input id="atlas-v5-from-email" name="from_email" type="email" value="" autocomplete="off"></td></tr>
                <tr><th scope="row"><label for="atlas-v5-subject">Subject template</label></th><td><input id="atlas-v5-subject" name="subject_template" type="text" value="" maxlength="200" autocomplete="off" required></td></tr>
                <tr><th scope="row"><label for="atlas-v5-success">Success message</label></th><td><input id="atlas-v5-success" name="success_message" type="text" value="" maxlength="500" autocomplete="off" required></td></tr>
                <tr><th scope="row"><label for="atlas-v5-failure">Failure message</label></th><td><input id="atlas-v5-failure" name="failure_message" type="text" value="" maxlength="500" autocomplete="off" required></td></tr>
                <tr><th scope="row"><label for="atlas-v5-sixth">Optional Email field</label></th><td><select id="atlas-v5-sixth" name="optional_sixth_field_mode"><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></td></tr>
                <tr><th scope="row"><label for="atlas-v5-reply-to">Valid customer Email as Reply-To</label></th><td><select id="atlas-v5-reply-to" name="reply_to_mode"><option value="enabled">Enabled</option><option value="disabled">Disabled</option></select></td></tr>
            </tbody></table>
            <?php submit_button('Save disabled configuration', 'primary', ''); ?>
        </form>

        <h2>Page 8 governed Email field</h2>
        <table class="widefat striped" data-atlas-v5-page8-metadata-status>
            <tbody>
                <tr><th scope="row">Metadata valid</th><td><?php echo esc_html(atlas_performance_local_v5_form_delivery_admin_status_text($metadata['metadata_valid'])); ?></td></tr>
                <tr><th scope="row">Current SHA-256</th><td><?php echo esc_html(is_string($metadata['metadata_sha256']) ? $metadata['metadata_sha256'] : 'Unavailable'); ?></td></tr>
                <tr><th scope="row">Source exact</th><td><?php echo esc_html(atlas_performance_local_v5_form_delivery_admin_status_text($metadata['source_exact'])); ?></td></tr>
                <tr><th scope="row">Field count</th><td><?php echo esc_html(is_int($metadata['field_count']) ? (string) $metadata['field_count'] : 'Unavailable'); ?></td></tr>
                <tr><th scope="row">Governed Email present</th><td><?php echo esc_html(atlas_performance_local_v5_form_delivery_admin_status_text($metadata['governed_email_present'])); ?></td></tr>
                <tr><th scope="row">Disabled configuration ready</th><td><?php echo esc_html(atlas_performance_local_v5_form_delivery_admin_status_text($metadata['configuration_ready_disabled'])); ?></td></tr>
                <tr><th scope="row">Target SHA-256</th><td><?php echo esc_html(is_string($metadata['target_sha256']) ? $metadata['target_sha256'] : 'Unavailable'); ?></td></tr>
            </tbody>
        </table>
        <?php if ($metadata['upgrade_available'] === true): ?>
            <form method="post" action="<?php echo esc_url($action_url); ?>">
                <input type="hidden" name="action" value="<?php echo esc_attr(ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION); ?>">
                <input type="hidden" name="atlas_command" value="add_governed_customer_email">
                <input type="hidden" name="expected_prior_sha256" value="<?php echo esc_attr($metadata['metadata_sha256']); ?>">
                <?php wp_nonce_field(
                    ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION,
                    ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,
                    false,
                    true
                ); ?>
                <?php submit_button('Add governed Email field to Page 8', 'secondary', ''); ?>
            </form>
        <?php endif; ?>

        <h2>Delivery state</h2>
        <?php foreach ([
            'enable_delivery' => 'Enable delivery',
            'disable_delivery' => 'Disable delivery',
            'remove_disabled_configuration' => 'Remove disabled configuration',
        ] as $command => $label): ?>
            <form method="post" action="<?php echo esc_url($action_url); ?>">
                <input type="hidden" name="action" value="<?php echo esc_attr(ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION); ?>">
                <input type="hidden" name="atlas_command" value="<?php echo esc_attr($command); ?>">
                <?php wp_nonce_field(
                    ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_ACTION,
                    ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_NONCE_FIELD,
                    false,
                    true
                ); ?>
                <?php submit_button($label, 'secondary', ''); ?>
            </form>
        <?php endforeach; ?>
    </div>
    <?php
}

function atlas_performance_local_v5_form_delivery_admin_reject(): void {
    wp_die('The settings request was rejected.', 'Request rejected.', ['response' => 403]);
}

function atlas_performance_local_v5_form_delivery_admin_redirect(string $status): void {
    $allowed = [
        'saved', 'enabled', 'disabled', 'removed', 'rejected',
        'write_failed_prior_restored', 'write_failed_rollback_failed',
        'remove_failed_prior_restored', 'remove_failed_rollback_failed',
        'metadata_email_applied', 'metadata_email_unchanged',
        'metadata_email_rejected', 'metadata_email_verification_failed',
    ];
    if (!in_array($status, $allowed, true)) { $status = 'rejected'; }
    $url = add_query_arg(
        [
            'page' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_PAGE,
            'atlas_v5_form_status' => $status,
        ],
        admin_url('options-general.php')
    );
    wp_safe_redirect($url);
    exit;
}

function atlas_performance_local_v5_form_delivery_admin_handle_post(): void {
    $input = $_POST;
    if (!atlas_performance_local_v5_form_delivery_admin_request_is_authorized($input)) {
        atlas_performance_local_v5_form_delivery_admin_reject();
        return;
    }
    $command = atlas_performance_local_v5_form_delivery_admin_scalar($input, 'atlas_command');
    if ($command === 'replace_configuration') {
        $candidate = atlas_performance_local_v5_form_delivery_admin_candidate($input);
        if ($candidate === null) {
            atlas_performance_local_v5_form_delivery_admin_redirect('rejected');
            return;
        }
        atlas_performance_local_v5_form_delivery_admin_redirect(
            atlas_performance_local_v5_form_delivery_admin_write_verified($candidate)
        );
        return;
    }
    if ($command === 'remove_disabled_configuration') {
        atlas_performance_local_v5_form_delivery_admin_redirect(
            atlas_performance_local_v5_form_delivery_admin_remove_disabled_verified()
        );
        return;
    }
    if ($command === 'add_governed_customer_email') {
        atlas_performance_local_v5_form_delivery_admin_redirect(
            atlas_performance_local_v5_form_delivery_admin_apply_governed_customer_email(
                $input
            )
        );
        return;
    }
    $candidate = $command === 'enable_delivery'
        ? atlas_performance_local_v5_form_delivery_admin_enable_candidate()
        : atlas_performance_local_v5_form_delivery_admin_disable_candidate();
    if ($candidate === null) {
        atlas_performance_local_v5_form_delivery_admin_redirect('rejected');
        return;
    }
    $write_status = atlas_performance_local_v5_form_delivery_admin_write_verified($candidate);
    atlas_performance_local_v5_form_delivery_admin_redirect(
        $write_status === 'saved'
            ? ($command === 'enable_delivery' ? 'enabled' : 'disabled')
            : $write_status
    );
}
add_action(
    'admin_post_' . ATLAS_PERFORMANCE_LOCAL_V5_FORM_ADMIN_ACTION,
    'atlas_performance_local_v5_form_delivery_admin_handle_post'
);

function atlas_performance_local_v5_form_delivery_disable_page_cache(): void {
    if (is_admin() || !is_singular('page')) { return; }
    $post_id = get_queried_object_id();
    if (!is_int($post_id) || $post_id < 1) { return; }
    $payload = get_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, true);
    if (!is_array($payload) || atlas_performance_local_v5_form_delivery_config_for_payload($payload) === null) {
        return;
    }
    if (!defined('DONOTCACHEPAGE')) { define('DONOTCACHEPAGE', true); }
    nocache_headers();
    if (!headers_sent()) {
        header('Cache-Control: no-cache, must-revalidate, max-age=0, no-store, private', true);
    }
}
add_action('template_redirect', 'atlas_performance_local_v5_form_delivery_disable_page_cache', 0);

function atlas_performance_local_v5_form_delivery_base64url_encode(string $value): string {
    return rtrim(strtr(base64_encode($value), '+/', '-_'), '=');
}

function atlas_performance_local_v5_form_delivery_base64url_decode(string $value): ?string {
    if ($value === '' || preg_match('/^[A-Za-z0-9_-]+$/', $value) !== 1) { return null; }
    $padding = (4 - strlen($value) % 4) % 4;
    $decoded = base64_decode(strtr($value, '-_', '+/') . str_repeat('=', $padding), true);
    if (!is_string($decoded)
        || !hash_equals($value, atlas_performance_local_v5_form_delivery_base64url_encode($decoded))) {
        return null;
    }
    return $decoded;
}

function atlas_performance_local_v5_form_delivery_key(string $purpose): string {
    return hash_hmac('sha256', $purpose, wp_salt('auth'), true);
}

function atlas_performance_local_v5_form_delivery_uuid(): ?string {
    try { $bytes = random_bytes(16); }
    catch (Throwable $error) { return null; }
    $bytes[6] = chr((ord($bytes[6]) & 0x0f) | 0x40);
    $bytes[8] = chr((ord($bytes[8]) & 0x3f) | 0x80);
    $hex = bin2hex($bytes);
    return substr($hex, 0, 8) . '-' . substr($hex, 8, 4) . '-' . substr($hex, 12, 4)
        . '-' . substr($hex, 16, 4) . '-' . substr($hex, 20, 12);
}

function atlas_performance_local_v5_form_delivery_page_identity(int $post_id): string {
    return 'wordpress-page:' . $post_id;
}

function atlas_performance_local_v5_form_delivery_issue_token(
    array $payload,
    int $post_id,
    array $config,
    ?int $now = null
): ?string {
    $now = $now ?? time();
    $identity = atlas_performance_local_v5_form_delivery_uuid();
    if ($identity === null) { return null; }
    $claims = [
        'token_schema' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_TOKEN_SCHEMA,
        'website_identity' => $payload['website']['identity'],
        'form_identity' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY,
        'form_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION,
        'page_identity' => atlas_performance_local_v5_form_delivery_page_identity($post_id),
        'field_definition_hash' => atlas_performance_local_v5_form_delivery_hash_fields($payload['form']['fields']),
        'issued_at' => $now,
        'expires_at' => $now + $config['token_ttl_seconds'],
        'token_identity' => $identity,
    ];
    $json = atlas_performance_local_v5_form_delivery_canonical_json($claims);
    if ($json === null) { return null; }
    $encoded = atlas_performance_local_v5_form_delivery_base64url_encode($json);
    $signature = hash_hmac(
        'sha256',
        $encoded,
        atlas_performance_local_v5_form_delivery_key('project-atlas-v5-form-token@1'),
        true
    );
    return $encoded . '.' . atlas_performance_local_v5_form_delivery_base64url_encode($signature);
}

function atlas_performance_local_v5_form_delivery_verify_token_signature(string $token): ?array {
    if (strlen($token) > 4096 || substr_count($token, '.') !== 1) { return null; }
    [$encoded, $encoded_signature] = explode('.', $token, 2);
    $json = atlas_performance_local_v5_form_delivery_base64url_decode($encoded);
    $signature = atlas_performance_local_v5_form_delivery_base64url_decode($encoded_signature);
    if ($json === null || $signature === null || strlen($signature) !== 32) { return null; }
    $expected = hash_hmac(
        'sha256',
        $encoded,
        atlas_performance_local_v5_form_delivery_key('project-atlas-v5-form-token@1'),
        true
    );
    if (!hash_equals($expected, $signature)) { return null; }
    try { $claims = json_decode($json, true, 16, JSON_THROW_ON_ERROR); }
    catch (JsonException $error) { return null; }
    if (!atlas_performance_local_v5_form_delivery_exact_record($claims, [
        'token_schema', 'website_identity', 'form_identity', 'form_version',
        'page_identity', 'field_definition_hash', 'issued_at', 'expires_at',
        'token_identity',
    ])) { return null; }
    $canonical = atlas_performance_local_v5_form_delivery_canonical_json($claims);
    if ($canonical === null || !hash_equals($json, $canonical)) { return null; }
    return $claims;
}

function atlas_performance_local_v5_form_delivery_validate_token(
    string $token,
    array $payload,
    int $post_id,
    array $config,
    ?int $now = null
): ?array {
    $claims = atlas_performance_local_v5_form_delivery_verify_token_signature($token);
    $now = $now ?? time();
    if ($claims === null
        || $claims['token_schema'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_TOKEN_SCHEMA
        || $claims['website_identity'] !== $payload['website']['identity']
        || $claims['website_identity'] !== $config['website_identity']
        || $claims['form_identity'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY
        || $claims['form_identity'] !== $config['form_identity']
        || $claims['form_version'] !== ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION
        || $claims['form_version'] !== $config['form_version']
        || $claims['page_identity'] !== atlas_performance_local_v5_form_delivery_page_identity($post_id)
        || $claims['field_definition_hash'] !== atlas_performance_local_v5_form_delivery_hash_fields($payload['form']['fields'])
        || $claims['field_definition_hash'] !== $config['field_definition_hash']
        || !is_int($claims['issued_at']) || !is_int($claims['expires_at'])
        || $claims['issued_at'] > $now || $claims['expires_at'] <= $now
        || $claims['expires_at'] - $claims['issued_at'] !== $config['token_ttl_seconds']
        || !is_string($claims['token_identity'])
        || preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/', $claims['token_identity']) !== 1) {
        return null;
    }
    return $claims;
}

function atlas_performance_local_v5_form_delivery_origin_tuple(string $url, bool $allow_path): ?array {
    if ($url === '' || str_starts_with($url, '//') || str_contains($url, '\\') || str_contains($url, ',')) { return null; }
    $parts = wp_parse_url($url);
    if (!is_array($parts) || isset($parts['user']) || isset($parts['pass'])
        || !isset($parts['scheme'], $parts['host'])) { return null; }
    $scheme = strtolower((string) $parts['scheme']);
    $host = strtolower((string) $parts['host']);
    if (!in_array($scheme, ['http', 'https'], true)
        || $host === ''
        || !(filter_var($host, FILTER_VALIDATE_IP)
            || preg_match('/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/', $host) === 1)) { return null; }
    if (!$allow_path && ((string) ($parts['path'] ?? '') !== '' || isset($parts['query']) || isset($parts['fragment']))) {
        return null;
    }
    $port = isset($parts['port']) ? (int) $parts['port'] : ($scheme === 'https' ? 443 : 80);
    if ($port < 1 || $port > 65535) { return null; }
    return [$scheme, $host, $port];
}

function atlas_performance_local_v5_form_delivery_expected_origin(): ?array {
    $home = home_url('/');
    return is_string($home)
        ? atlas_performance_local_v5_form_delivery_origin_tuple($home, true)
        : null;
}

function atlas_performance_local_v5_form_delivery_canonical_website_domain(): ?string {
    if (!defined('ATLAS_METADATA_CANONICAL_URL') || !is_string(ATLAS_METADATA_CANONICAL_URL)) {
        return null;
    }
    $parts = wp_parse_url(ATLAS_METADATA_CANONICAL_URL);
    if (!is_array($parts) || !isset($parts['scheme'], $parts['host'])
        || strtolower((string) $parts['scheme']) !== 'https') { return null; }
    $host = strtolower((string) $parts['host']);
    if (str_starts_with($host, 'www.')) { $host = substr($host, 4); }
    return preg_match('/^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?$/', $host) === 1
        ? $host
        : null;
}

function atlas_performance_local_v5_form_delivery_from_domain_is_allowed($email): bool {
    if (!is_string($email)) { return false; }
    $from_domain = atlas_performance_local_v5_form_delivery_email_domain($email);
    $expected = atlas_performance_local_v5_form_delivery_expected_origin();
    if ($from_domain === null || !is_array($expected) || !is_string($expected[1] ?? null)) {
        return false;
    }
    if (hash_equals($expected[1], $from_domain)) { return true; }
    if (!function_exists('wp_get_environment_type') || wp_get_environment_type() !== 'staging') {
        return false;
    }
    $canonical = atlas_performance_local_v5_form_delivery_canonical_website_domain();
    return is_string($canonical) && hash_equals($canonical, $from_domain);
}

function atlas_performance_local_v5_form_delivery_url_is_same_origin(string $url): bool {
    $expected = atlas_performance_local_v5_form_delivery_expected_origin();
    $actual = atlas_performance_local_v5_form_delivery_origin_tuple($url, true);
    return $expected !== null && $actual !== null && $expected === $actual;
}

function atlas_performance_local_v5_form_delivery_same_origin_request(WP_REST_Request $request): bool {
    $expected = atlas_performance_local_v5_form_delivery_expected_origin();
    if ($expected === null) { return false; }
    $origin = $request->get_header('origin');
    if (is_string($origin) && $origin !== '') {
        $actual = atlas_performance_local_v5_form_delivery_origin_tuple($origin, false);
        return $actual !== null && $actual === $expected;
    }
    if (is_string($origin) && $origin === '' && isset($_SERVER['HTTP_ORIGIN'])) { return false; }
    $referer = $request->get_header('referer');
    if (!is_string($referer) || $referer === '') { return false; }
    $actual = atlas_performance_local_v5_form_delivery_origin_tuple($referer, true);
    return $actual !== null && $actual === $expected;
}

function atlas_performance_local_v5_form_delivery_render_context(array $form): ?array {
    if (!function_exists('atlas_performance_local_v5_current_payload')) { return null; }
    $payload = atlas_performance_local_v5_current_payload();
    $post_id = get_queried_object_id();
    if (!is_array($payload) || !is_int($post_id) || $post_id < 1
        || !in_array($payload['surface'], ['city_service', 'estimate'], true)
        || $payload['form'] !== $form) { return null; }
    $config = atlas_performance_local_v5_form_delivery_config_for_payload($payload);
    if ($config === null) { return null; }
    $endpoint = rest_url(
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE_NAMESPACE
        . ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE
    );
    if (!is_string($endpoint) || !atlas_performance_local_v5_form_delivery_url_is_same_origin($endpoint)) { return null; }
    $token = atlas_performance_local_v5_form_delivery_issue_token($payload, $post_id, $config);
    if ($token === null) { return null; }
    return [
        'endpoint' => $endpoint,
        'token' => $token,
        'website_identity' => $payload['website']['identity'],
        'form_identity' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDENTITY,
        'form_version' => ATLAS_PERFORMANCE_LOCAL_V5_FORM_VERSION,
        'page_identity' => atlas_performance_local_v5_form_delivery_page_identity($post_id),
        'field_definition_hash' => atlas_performance_local_v5_form_delivery_hash_fields($form['fields']),
    ];
}

function atlas_performance_local_v5_form_delivery_matching_page_exists(array $config): bool {
    $ids = get_posts([
        'post_type' => 'page',
        'post_status' => 'publish',
        'posts_per_page' => -1,
        'fields' => 'ids',
        'meta_key' => ATLAS_PERFORMANCE_LOCAL_V5_META_KEY,
        'no_found_rows' => true,
    ]);
    foreach ($ids as $post_id) {
        $payload = get_post_meta((int) $post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, true);
        if (is_array($payload)
            && atlas_performance_local_v5_form_delivery_config_for_payload($payload) === $config) {
            return true;
        }
    }
    return false;
}

function atlas_performance_local_v5_form_delivery_register_route(): void {
    $config = get_option(ATLAS_PERFORMANCE_LOCAL_V5_FORM_DELIVERY_OPTION, null);
    if (!is_array($config) || ($config['enabled'] ?? null) !== true
        || !atlas_performance_local_v5_form_delivery_matching_page_exists($config)) { return; }
    register_rest_route(
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE_NAMESPACE,
        ATLAS_PERFORMANCE_LOCAL_V5_FORM_ROUTE,
        [
            'methods' => WP_REST_Server::CREATABLE,
            'permission_callback' => 'atlas_performance_local_v5_form_delivery_permission',
            'callback' => 'atlas_performance_local_v5_form_delivery_submit',
        ]
    );
}
add_action('rest_api_init', 'atlas_performance_local_v5_form_delivery_register_route');

function atlas_performance_local_v5_form_delivery_public_error(int $status): WP_Error {
    return new WP_Error(
        'atlas_v5_estimate_request_rejected',
        'The estimate request could not be accepted.',
        ['status' => $status]
    );
}

function atlas_performance_local_v5_form_delivery_permission(WP_REST_Request $request) {
    if ($request->get_method() !== 'POST') { return atlas_performance_local_v5_form_delivery_public_error(405); }
    $content_type = $request->get_header('content-type');
    if (!is_string($content_type)
        || preg_match('/^application\/json(?:\s*;\s*charset=utf-8)?$/i', trim($content_type)) !== 1) {
        return atlas_performance_local_v5_form_delivery_public_error(415);
    }
    $raw = $request->get_body();
    $declared = $request->get_header('content-length');
    if (!is_string($raw) || $raw === '' || strlen($raw) > ATLAS_PERFORMANCE_LOCAL_V5_FORM_MAX_BODY_BYTES
        || is_string($declared) && $declared !== ''
            && (preg_match('/^[0-9]+$/', $declared) !== 1
                || (int) $declared > ATLAS_PERFORMANCE_LOCAL_V5_FORM_MAX_BODY_BYTES)) {
        return atlas_performance_local_v5_form_delivery_public_error(413);
    }
    if (!atlas_performance_local_v5_form_delivery_same_origin_request($request)) {
        return atlas_performance_local_v5_form_delivery_public_error(403);
    }
    return true;
}

function atlas_performance_local_v5_form_delivery_response(array $body, int $status = 200): WP_REST_Response {
    $response = new WP_REST_Response($body, $status);
    $response->header('Cache-Control', 'no-store, private, max-age=0');
    $response->header('X-Content-Type-Options', 'nosniff');
    return $response;
}

function atlas_performance_local_v5_form_delivery_safe_response(
    string $state,
    string $message,
    int $status
): WP_REST_Response {
    return atlas_performance_local_v5_form_delivery_response([
        'ok' => $state === 'success' || $state === 'duplicate',
        'state' => $state,
        'message' => $message,
    ], $status);
}

function atlas_performance_local_v5_form_delivery_parse_request(WP_REST_Request $request): ?array {
    try { $body = json_decode($request->get_body(), true, 16, JSON_THROW_ON_ERROR); }
    catch (JsonException $error) { return null; }
    if (!atlas_performance_local_v5_form_delivery_exact_record($body, [
        'token', 'idempotency_identity', 'website_identity', 'form_identity',
        'form_version', 'page_identity', 'field_definition_hash', 'honeypot', 'fields',
    ])) { return null; }
    if (!is_string($body['token']) || $body['token'] === '' || strlen($body['token']) > 4096
        || !is_string($body['idempotency_identity'])
        || preg_match('/^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/', $body['idempotency_identity']) !== 1
        || !is_string($body['website_identity'])
        || !is_string($body['form_identity'])
        || !is_int($body['form_version'])
        || !is_string($body['page_identity'])
        || !is_string($body['field_definition_hash'])
        || preg_match('/^[a-f0-9]{64}$/', $body['field_definition_hash']) !== 1
        || !is_string($body['honeypot']) || strlen($body['honeypot']) > 200
        || !is_array($body['fields']) || array_is_list($body['fields'])) { return null; }
    return $body;
}

function atlas_performance_local_v5_form_delivery_page_context(string $identity): ?array {
    if (preg_match('/^wordpress-page:([1-9][0-9]*)$/', $identity, $matches) !== 1) { return null; }
    $post_id = (int) $matches[1];
    $post = get_post($post_id);
    if (!$post instanceof WP_Post || $post->post_type !== 'page' || $post->post_status !== 'publish') { return null; }
    $payload = get_post_meta($post_id, ATLAS_PERFORMANCE_LOCAL_V5_META_KEY, true);
    if (!is_array($payload) || !function_exists('atlas_performance_local_v5_payload_is_valid')
        || !atlas_performance_local_v5_payload_is_valid($payload)
        || !in_array($payload['surface'], ['city_service', 'estimate'], true)) { return null; }
    $config = atlas_performance_local_v5_form_delivery_config_for_payload($payload);
    return $config === null ? null : [$post_id, $post, $payload, $config];
}

function atlas_performance_local_v5_form_delivery_character_length(string $value): int {
    return function_exists('mb_strlen') ? mb_strlen($value, 'UTF-8') : strlen($value);
}

function atlas_performance_local_v5_form_delivery_normalize_value($value, array $field): ?string {
    if (!is_string($value) || wp_check_invalid_utf8($value, true) !== $value) { return null; }
    $value = str_replace(["\r\n", "\r"], "\n", $value);
    $rule = $field['validation']['rule'];
    if ($rule !== 'free_text' && str_contains($value, "\n")) { return null; }
    if (preg_match($rule === 'free_text' ? '/[\x00-\x09\x0B-\x1F\x7F]/u' : '/[\x00-\x1F\x7F]/u', $value) === 1) { return null; }
    $value = trim($value);
    if ($value === '' && !$field['required']) { return ''; }
    $length = atlas_performance_local_v5_form_delivery_character_length($value);
    if ($length < $field['validation']['minimum_length'] || $length > $field['maximum_length']) { return null; }
    if ($field['required'] && $value === '') { return null; }
    if ($rule === 'phone') {
        if (preg_match('/^[0-9+(). xXextEXT-]+$/', $value) !== 1
            || preg_match_all('/[0-9]/', $value) < 6) { return null; }
    } elseif ($rule === 'postal_code' && preg_match('/^[A-Za-z0-9][A-Za-z0-9 -]{3,10}[A-Za-z0-9]$/', $value) !== 1) {
        return null;
    } elseif ($rule === 'email_address' && $value !== '' && !atlas_performance_local_v5_form_delivery_email($value)) {
        return null;
    }
    return $value;
}

function atlas_performance_local_v5_form_delivery_validate_fields($values, array $definitions): ?array {
    if (!is_array($values) || array_is_list($values) || !atlas_performance_local_v5_form_delivery_default_field_contract($definitions)) { return null; }
    $expected = array_map(static fn(array $field): string => $field['field_key'], $definitions);
    $actual = array_keys($values);
    sort($expected, SORT_STRING);
    sort($actual, SORT_STRING);
    if ($expected !== $actual) { return null; }
    $normalized = [];
    foreach ($definitions as $field) {
        $value = atlas_performance_local_v5_form_delivery_normalize_value($values[$field['field_key']], $field);
        if ($value === null) { return null; }
        $normalized[$field['field_key']] = $value;
    }
    return $normalized;
}

function atlas_performance_local_v5_form_delivery_metadata_hash(string $purpose, array $values): string {
    $json = atlas_performance_local_v5_form_delivery_canonical_json($values);
    return hash_hmac(
        'sha256',
        $json ?? '',
        atlas_performance_local_v5_form_delivery_key($purpose)
    );
}

function atlas_performance_local_v5_form_delivery_idempotency_option(array $config, string $identity): string {
    return ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDEMPOTENCY_PREFIX
        . atlas_performance_local_v5_form_delivery_metadata_hash(
            'project-atlas-v5-form-idempotency@1',
            [
                'website_identity' => $config['website_identity'],
                'form_identity' => $config['form_identity'],
                'idempotency_identity' => $identity,
            ]
        );
}

function atlas_performance_local_v5_form_delivery_idempotency_status(
    string $option_name,
    int $now
): ?string {
    $record = get_option($option_name, null);
    if (!atlas_performance_local_v5_form_delivery_exact_record($record, ['state', 'expires_at'])
        || !is_string($record['state']) || !is_int($record['expires_at'])) { return null; }
    if ($record['expires_at'] <= $now) {
        delete_option($option_name);
        return null;
    }
    return in_array($record['state'], ['pending', 'delivered'], true) ? $record['state'] : 'pending';
}

function atlas_performance_local_v5_form_delivery_schedule_cleanup(string $option_name, int $expires_at): void {
    if (function_exists('wp_schedule_single_event')) {
        wp_schedule_single_event(
            $expires_at + 1,
            ATLAS_PERFORMANCE_LOCAL_V5_FORM_CLEANUP_HOOK,
            [$option_name, $expires_at]
        );
    }
}

function atlas_performance_local_v5_form_delivery_claim_idempotency(
    string $option_name,
    int $expires_at
): bool {
    $claimed = add_option(
        $option_name,
        ['state' => 'pending', 'expires_at' => $expires_at],
        '',
        false
    );
    if ($claimed) { atlas_performance_local_v5_form_delivery_schedule_cleanup($option_name, $expires_at); }
    return $claimed;
}

function atlas_performance_local_v5_form_delivery_mark_delivered(string $option_name, int $expires_at): void {
    update_option($option_name, ['state' => 'delivered', 'expires_at' => $expires_at], false);
}

function atlas_performance_local_v5_form_delivery_cleanup_metadata(string $option_name, int $expires_at): void {
    if ((!str_starts_with($option_name, ATLAS_PERFORMANCE_LOCAL_V5_FORM_IDEMPOTENCY_PREFIX)
            && !str_starts_with($option_name, ATLAS_PERFORMANCE_LOCAL_V5_FORM_RATE_LOCK_PREFIX))
        || preg_match('/^[A-Za-z0-9_]+$/', $option_name) !== 1) { return; }
    $record = get_option($option_name, null);
    if (is_array($record) && ($record['expires_at'] ?? null) === $expires_at && $expires_at <= time()) {
        delete_option($option_name);
    }
}
add_action(
    ATLAS_PERFORMANCE_LOCAL_V5_FORM_CLEANUP_HOOK,
    'atlas_performance_local_v5_form_delivery_cleanup_metadata',
    10,
    2
);

function atlas_performance_local_v5_form_delivery_rate_allowed(
    array $config,
    int $now
): bool {
    $address = isset($_SERVER['REMOTE_ADDR']) && is_string($_SERVER['REMOTE_ADDR'])
        ? $_SERVER['REMOTE_ADDR']
        : 'unknown';
    if (strlen($address) > 128) { $address = 'unknown'; }
    $window = intdiv($now, $config['rate_window_seconds']);
    $digest = atlas_performance_local_v5_form_delivery_metadata_hash(
        'project-atlas-v5-form-rate@1',
        [
            'address' => $address,
            'website_identity' => $config['website_identity'],
            'form_identity' => $config['form_identity'],
            'window' => $window,
        ]
    );
    $transient = ATLAS_PERFORMANCE_LOCAL_V5_FORM_RATE_PREFIX . $digest;
    $lock = ATLAS_PERFORMANCE_LOCAL_V5_FORM_RATE_LOCK_PREFIX . $digest;
    $lock_expiry = $now + 10;
    $existing_lock = get_option($lock, null);
    if (is_array($existing_lock) && is_int($existing_lock['expires_at'] ?? null)
        && $existing_lock['expires_at'] <= $now) { delete_option($lock); }
    if (!add_option($lock, ['expires_at' => $lock_expiry], '', false)) { return false; }
    atlas_performance_local_v5_form_delivery_schedule_cleanup($lock, $lock_expiry);
    try {
        $record = get_transient($transient);
        $expires_at = ($window + 1) * $config['rate_window_seconds'];
        if (!atlas_performance_local_v5_form_delivery_exact_record($record, ['count', 'expires_at'])
            || !is_int($record['count']) || !is_int($record['expires_at'])
            || $record['expires_at'] <= $now) {
            $record = ['count' => 0, 'expires_at' => $expires_at];
        }
        $record['count']++;
        if (set_transient($transient, $record, max(1, $expires_at - $now)) !== true) {
            return false;
        }
        return $record['count'] <= $config['rate_max_attempts'];
    } finally {
        delete_option($lock);
    }
}

function atlas_performance_local_v5_form_delivery_subject(
    array $config,
    array $payload
): ?string {
    $subject = strtr($config['subject_template'], [
        '{{company_name}}' => $payload['website']['company_name'],
        '{{page_title}}' => $payload['page']['title'],
        '{{site_name}}' => get_bloginfo('name'),
    ]);
    return atlas_performance_local_v5_form_delivery_one_line($subject, 240) ? $subject : null;
}

function atlas_performance_local_v5_form_delivery_submission_reference(): ?string {
    try { return 'REF-' . strtoupper(substr(hash('sha256', random_bytes(32)), 0, 16)); }
    catch (Throwable $error) { return null; }
}

function atlas_performance_local_v5_form_delivery_mail_body(
    array $payload,
    int $post_id,
    array $fields,
    string $reference,
    int $now
): ?string {
    $url = get_permalink($post_id);
    if (!is_string($url) || !atlas_performance_local_v5_form_delivery_url_is_same_origin($url)) { return null; }
    $lines = [
        'Website: ' . $payload['website']['company_name'],
        'Page: ' . $payload['page']['title'],
        'Originating URL: ' . $url,
        'Submitted: ' . wp_date(DATE_ATOM, $now, wp_timezone()),
        '',
        'Name: ' . $fields['name'],
        'Phone: ' . $fields['phone'],
        'ZIP code: ' . $fields['postal-code'],
        'Requested service: ' . $fields['requested-service'],
    ];
    if ($fields['message'] !== '') {
        $lines[] = 'Optional message:';
        $lines[] = $fields['message'];
    }
    if (count($payload['form']['fields']) === 6) {
        $sixth = $payload['form']['fields'][5];
        if ($fields[$sixth['field_key']] !== '') {
            $lines[] = $sixth['label'] . ': ' . $fields[$sixth['field_key']];
        }
    }
    $lines[] = '';
    $lines[] = 'Submission reference: ' . $reference;
    return implode("\n", $lines);
}

function atlas_performance_local_v5_form_delivery_send_mail(
    array $config,
    array $payload,
    int $post_id,
    array $fields,
    int $now
): bool {
    $subject = atlas_performance_local_v5_form_delivery_subject($config, $payload);
    $reference = atlas_performance_local_v5_form_delivery_submission_reference();
    if ($subject === null || $reference === null) { return false; }
    $body = atlas_performance_local_v5_form_delivery_mail_body(
        $payload,
        $post_id,
        $fields,
        $reference,
        $now
    );
    if ($body === null) { return false; }
    $headers = [];
    if ($config['reply_to']['enabled']) {
        $field_key = $config['reply_to']['field_key'];
        $reply_to = is_string($field_key) ? ($fields[$field_key] ?? '') : '';
        if ($reply_to !== '' && atlas_performance_local_v5_form_delivery_email($reply_to)) {
            $headers[] = 'Reply-To: ' . $reply_to;
        }
    }
    $from_email = static fn(string $unused): string => $config['from_email'];
    $from_name = static fn(string $unused): string => $config['from_name'];
    $content_type = static fn(string $unused): string => 'text/plain';
    add_filter('wp_mail_from', $from_email, 999);
    add_filter('wp_mail_from_name', $from_name, 999);
    add_filter('wp_mail_content_type', $content_type, 999);
    try {
        return wp_mail($config['recipient_email'], $subject, $body, $headers) === true;
    } catch (Throwable $error) {
        return false;
    } finally {
        remove_filter('wp_mail_from', $from_email, 999);
        remove_filter('wp_mail_from_name', $from_name, 999);
        remove_filter('wp_mail_content_type', $content_type, 999);
    }
}

function atlas_performance_local_v5_form_delivery_submit(WP_REST_Request $request) {
    $permission = atlas_performance_local_v5_form_delivery_permission($request);
    if (is_wp_error($permission)) { return $permission; }
    $body = atlas_performance_local_v5_form_delivery_parse_request($request);
    if ($body === null) { return atlas_performance_local_v5_form_delivery_public_error(422); }
    $signed_claims = atlas_performance_local_v5_form_delivery_verify_token_signature($body['token']);
    if ($signed_claims === null || ($signed_claims['page_identity'] ?? null) !== $body['page_identity']) {
        return atlas_performance_local_v5_form_delivery_public_error(403);
    }
    $context = atlas_performance_local_v5_form_delivery_page_context($body['page_identity']);
    if ($context === null) { return atlas_performance_local_v5_form_delivery_public_error(403); }
    [$post_id, $post, $payload, $config] = $context;
    if ($body['website_identity'] !== $config['website_identity']
        || $body['website_identity'] !== $payload['website']['identity']
        || $body['form_identity'] !== $config['form_identity']
        || $body['form_version'] !== $config['form_version']
        || $body['field_definition_hash'] !== $config['field_definition_hash']
        || atlas_performance_local_v5_form_delivery_validate_token(
            $body['token'],
            $payload,
            $post_id,
            $config
        ) === null) {
        return atlas_performance_local_v5_form_delivery_public_error(403);
    }
    if ($body['honeypot'] !== '') {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'success',
            $config['success_message'],
            200
        );
    }
    $fields = atlas_performance_local_v5_form_delivery_validate_fields(
        $body['fields'],
        $payload['form']['fields']
    );
    if ($fields === null) {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'validation_error',
            ATLAS_PERFORMANCE_LOCAL_V5_FORM_VALIDATION_MESSAGE,
            422
        );
    }
    $now = time();
    $idempotency_option = atlas_performance_local_v5_form_delivery_idempotency_option(
        $config,
        $body['idempotency_identity']
    );
    $idempotency_status = atlas_performance_local_v5_form_delivery_idempotency_status(
        $idempotency_option,
        $now
    );
    if ($idempotency_status === 'delivered') {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'duplicate',
            $config['success_message'],
            200
        );
    }
    if ($idempotency_status === 'pending') {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'pending',
            $config['failure_message'],
            409
        );
    }
    if (!atlas_performance_local_v5_form_delivery_rate_allowed($config, $now)) {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'rate_limited',
            $config['failure_message'],
            429
        );
    }
    $pending_expires_at = $now + ATLAS_PERFORMANCE_LOCAL_V5_FORM_PENDING_LEASE_SECONDS;
    if (!atlas_performance_local_v5_form_delivery_claim_idempotency($idempotency_option, $pending_expires_at)) {
        return atlas_performance_local_v5_form_delivery_safe_response(
            'pending',
            $config['failure_message'],
            409
        );
    }
    $sent = atlas_performance_local_v5_form_delivery_send_mail(
        $config,
        $payload,
        $post_id,
        $fields,
        $now
    );
    if (!$sent) {
        delete_option($idempotency_option);
        return atlas_performance_local_v5_form_delivery_safe_response(
            'mail_failure',
            $config['failure_message'],
            503
        );
    }
    $expires_at = $now + $config['idempotency_ttl_seconds'];
    atlas_performance_local_v5_form_delivery_mark_delivered($idempotency_option, $expires_at);
    atlas_performance_local_v5_form_delivery_schedule_cleanup($idempotency_option, $expires_at);
    return atlas_performance_local_v5_form_delivery_safe_response(
        'success',
        $config['success_message'],
        200
    );
}
