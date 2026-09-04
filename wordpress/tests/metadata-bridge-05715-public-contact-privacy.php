<?php
declare(strict_types=1);

/**
 * Process-local proof for the 0.57.15 Page 8 governed-public-contact exception.
 * All addresses are reserved synthetic fixtures.
 */

final class WP_Post {}
final class WP_Error {}
final class WP_REST_Request {}
final class WP_REST_Response {}

define('ABSPATH', __DIR__ . '/');
define('ATLAS_METADATA_BRIDGE_VERSION', '0.57.15');

$public_contact = 'public-contact' . '@' . 'example.test';
$private_from = 'private-from' . '@' . 'example.test';
$other_recipient = 'other-recipient' . '@' . 'example.test';
$GLOBALS['atlas_public_contact_privacy_test'] = [
    'checks' => [],
    'config' => [
        'recipient_email' => $public_contact,
        'from_email' => $private_from,
    ],
];

function add_action(string $hook, $callback): bool { return true; }
function get_option(string $name, $default = false) {
    return $GLOBALS['atlas_public_contact_privacy_test']['config'] ?? $default;
}
function wp_json_encode($value, int $flags = 0, int $depth = 512) {
    return json_encode($value, $flags, $depth);
}

require dirname(__DIR__)
    . '/project-atlas-metadata-bridge-0.57.15/includes/performance-local-v5-page-payload.php';

function atlas_public_contact_privacy_check(bool $condition, string $identity): void {
    if (!$condition) { throw new RuntimeException($identity); }
    $GLOBALS['atlas_public_contact_privacy_test']['checks'][] = $identity;
}

$prior = [
    'website' => ['contact_email' => $public_contact],
    'footer' => ['contact_email' => $public_contact],
    'hero' => ['introduction' => 'Synthetic governed introduction.'],
];
$candidate = $prior;
atlas_public_contact_privacy_check(
    !atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        $prior
    ),
    'byte_preserved_governed_public_contact_allowed'
);

$extra_occurrence = $candidate;
$extra_occurrence['hero']['introduction'] .= ' ' . $public_contact;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $extra_occurrence,
        $prior
    ),
    'recipient_elsewhere_rejected'
);

$mismatched_footer = $candidate;
$mismatched_footer['footer']['contact_email'] = $other_recipient;
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $mismatched_footer,
        $prior
    ),
    'nonmatching_public_contact_paths_rejected'
);

atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        null
    ),
    'missing_valid_prior_rejected'
);

$GLOBALS['atlas_public_contact_privacy_test']['config'] = [
    'recipient_email' => $other_recipient,
    'from_email' => $public_contact,
];
atlas_public_contact_privacy_check(
    atlas_performance_local_v5_page_payload_contains_private_delivery_value(
        $candidate,
        $prior
    ),
    'from_address_rejected_even_at_public_contact_paths'
);

echo json_encode([
    'status' => 'PASS',
    'version' => ATLAS_METADATA_BRIDGE_VERSION,
    'check_count' => count($GLOBALS['atlas_public_contact_privacy_test']['checks']),
    'private_values_redacted' => true,
], JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n";
